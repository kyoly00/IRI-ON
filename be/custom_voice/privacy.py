"""STT 결과가 LLM/로그로 넘어가기 전에 적용하는 PII 필터.

이 필터는 텍스트 경계의 유출을 막는다. 외부 STT를 선택한 경우 원본 음성은 STT
사업자에게 전송된 뒤에야 텍스트가 생기므로, 음성 자체의 외부 전송까지 막으려면
``providers.py``의 STT 구현을 온프레미스 모델로 교체해야 한다.
"""

from __future__ import annotations

import re


class PIIRedactor:
    """한국 서비스에서 자주 나오는 개인정보 패턴을 결정적으로 마스킹한다."""

    _patterns: tuple[tuple[re.Pattern[str], str], ...] = (
        # 주민등록번호: 하이픈 유무와 뒤 7자리를 모두 포괄한다.
        (re.compile(r"(?<!\d)\d{6}\s*-?\s*[1-4]\d{6}(?!\d)"), "[주민등록번호]"),
        # 국내 휴대전화/대표 전화번호: 공백 또는 하이픈 표기를 허용한다.
        (re.compile(r"(?<!\d)01[016789][\s-]?\d{3,4}[\s-]?\d{4}(?!\d)"), "[전화번호]"),
        (re.compile(r"(?<!\d)0\d{1,2}[\s-]?\d{3,4}[\s-]?\d{4}(?!\d)"), "[전화번호]"),
        # 이메일 주소는 로컬 파트와 도메인을 통째로 숨긴다.
        (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[이메일]"),
        # 카드번호로 오인할 수 있는 13~19자리 묶음은 숫자 구분자를 포함해 숨긴다.
        (re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "[카드번호]"),
    )

    def redact(self, text: str) -> str:
        """알려진 PII 패턴을 의미만 남는 토큰으로 바꾼다."""

        sanitized = text
        for pattern, replacement in self._patterns:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized
