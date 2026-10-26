/** Convert browser-specific microphone failures into actionable user messages. */
function microphoneFailure(reason: unknown): Error {
  const name = reason instanceof DOMException
    ? reason.name
    : typeof reason === "object" && reason !== null && "name" in reason
      ? String((reason as { name?: unknown }).name || "")
      : "";

  if (name === "NotAllowedError" || name === "SecurityError") {
    return new Error(
      "마이크 권한이 차단되어 있습니다. 브라우저 주소창의 사이트 설정에서 마이크를 '허용'으로 바꾼 뒤 새로고침해 주세요. 카카오톡·인스타그램 등의 내장 브라우저라면 Chrome 또는 Safari에서 직접 열어 주세요.",
    );
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return new Error("사용할 수 있는 마이크를 찾지 못했습니다. 마이크 연결과 기기 설정을 확인해 주세요.");
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return new Error("마이크를 다른 앱이 사용 중이거나 운영체제에서 차단했습니다. 다른 앱을 닫고 다시 시도해 주세요.");
  }
  if (name === "OverconstrainedError") {
    return new Error("이 기기에서 요청한 마이크 설정을 지원하지 않습니다. 다른 마이크나 브라우저로 시도해 주세요.");
  }
  return reason instanceof Error ? reason : new Error(String(reason));
}

export async function requestMicrophone(
  constraints: MediaStreamConstraints,
): Promise<MediaStream> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("마이크는 HTTPS로 접속한 Chrome 또는 Safari에서 사용할 수 있습니다.");
  }

  const policy = (document as Document & {
    permissionsPolicy?: { allowsFeature: (feature: string) => boolean };
  }).permissionsPolicy;
  if (policy && !policy.allowsFeature("microphone")) {
    throw new Error(
      "현재 열린 화면에서는 마이크 사용이 허용되지 않습니다. 미리보기나 내장 화면을 닫고 서비스 주소를 새 탭에서 직접 열어 주세요.",
    );
  }

  try {
    return await navigator.mediaDevices.getUserMedia(constraints);
  } catch (reason) {
    throw microphoneFailure(reason);
  }
}
