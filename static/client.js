
(async () => {
  const canvas = document.getElementById('c');
  const ctx    = canvas.getContext('2d');

  function resizeCanvas() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width  = w;
    canvas.height = h;
    canvas.style.width  = `${w}px`;
    canvas.style.height = `${h}px`;
  }
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  function drawBitmap(bm) {
    ctx.drawImage(bm, 0, 0, canvas.width, canvas.height);
    bm.close();
  }

  // Negotiate codecs 
  async function negotiate() {
    const offer = [];
    if ('VideoDecoder' in window) {
      const candidates = [
        'vp09.00.10.08',   // VP9
        'hev1.1.6.L93.B0', // HEVC
        'avc1.42001E',     // H.264
        'vp8'              // VP8
      ];
      for (let cs of candidates) {
        try {
          const { supported } = await VideoDecoder.isConfigSupported({ codec: cs });
          if (supported) offer.push(cs);
        } catch { 
          /* ignore unsupported */ 
        }
      }
    }
    // Always fall back to MJPEG
    offer.push('mjpeg');
    console.log('sending offer:', offer);
    return offer;
  }

  const offer = await negotiate();

  // Open WebSocket
  const ws = new WebSocket(
    (location.protocol === 'https:' ? 'wss://' : 'ws://') +
    location.hostname + ':8767'
  );
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => {
    ws.send(JSON.stringify({ codecs: offer }));
  };

  // State & handlers
  let codec        = null;
  let decoder      = null;
  let gotKey       = false;
  let latestBytes  = null; // Will hold { data: Uint8Array, pts: BigInt }
  let mjpegBusy    = false;

  ws.onmessage = ev => {
    if (typeof ev.data === 'string') {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'config') {
        codec  = msg.codec;
        gotKey = false; // Reset gotKey state when a new codec config arrives

        if (codec !== 'mjpeg') {
          // Initialize or reconfigure WebCodecs decoder for non-MJPEG codecs
          decoder?.close?.();
          decoder = new VideoDecoder({
            output: frame => {
              // Try to draw the VideoFrame directly; fallback to createImageBitmap if unsupported
              try {
                ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
                frame.close();
              } catch {
                createImageBitmap(frame)
                  .then(drawBitmap)
                  .catch(console.error)
                  .finally(() => frame.close());
              }
            },
            error: e => {
              console.error('Decoder error:', e);
              decoder?.close?.();
              decoder = null;
              gotKey = false;
              // If desired, trigger re-negotiation here
            }
          });

          decoder.configure({
            codec,
            optimizeForLatency: true
          });
        }
      }
      return;
    }

    // Binary frames: strip 8-byte PTS header and store both payload + PTS
    const arr = new Uint8Array(ev.data);
    const dv  = new DataView(ev.data, 0, 8);
    const serverPTS = dv.getBigUint64(0, false); // big-endian
    const payload   = arr.subarray(8);
    latestBytes     = { data: payload, pts: serverPTS };
  };

  // Render loop
  function render() {
    if (codec === 'mjpeg') {
      // MJPEG path: only decode one frame at a time, drop stale data
      if (latestBytes && !mjpegBusy) {
        mjpegBusy   = true;
        const { data } = latestBytes;
        latestBytes   = null;

        createImageBitmap(new Blob([data], { type: 'image/jpeg' }))
          .then(drawBitmap)
          .catch(console.error)
          .finally(() => { mjpegBusy = false; });
      }

    } else if (
      decoder &&
      latestBytes &&
      decoder.decodeQueueSize <= 3   // allow up to 3 pending decodes
    ) {
      const { data, pts } = latestBytes;
      // Determine if this is a key frame by inspecting NALU header (H.264 IDR = NAL type 5)
      const isKey = ((data[4] & 0x1F) === 5);
      const chunk = new EncodedVideoChunk({
        type:      isKey ? 'key' : 'delta',
        timestamp: 0,
        data:      data
      });
      decoder.decode(chunk);
      gotKey       = gotKey || isKey;
      latestBytes  = null;
    }

    requestAnimationFrame(render);
  }
  requestAnimationFrame(render);

  // Fullscreen toggle
  canvas.addEventListener('pointerup', () => {
    if (!document.fullscreenElement) {
      canvas.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, { passive: true });

  ws.onerror = e  => console.error('WS error', e);
  ws.onclose = () => console.log('WS closed');
})();
