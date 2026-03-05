/**
 * 브라우저 AudioBuffer에서 오는 Base64 PCM 문자열을 Float32Array로 변환한다.
 */
export function base64ToFloat32Array(b64){
  const clean = b64.includes(",") ? b64.split(",")[1] : b64;
  const bin = atob(clean);
  const bytes = new Uint8Array(bin.length);
  for (let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}

/**
 * Web Audio API의 Float32Array 샘플을 16bit PCM(Int16Array)으로 변환한다.
 */
export function float32ToPcm16(f32){
  const out = new Int16Array(f32.length);
  for (let i=0;i<f32.length;i++){
    let s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
