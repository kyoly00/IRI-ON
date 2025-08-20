export function base64ToFloat32Array(b64){
  const clean = b64.includes(",") ? b64.split(",")[1] : b64;
  const bin = atob(clean);
  const bytes = new Uint8Array(bin.length);
  for (let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}
export function float32ToPcm16(f32){
  const out = new Int16Array(f32.length);
  for (let i=0;i<f32.length;i++){
    let s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
