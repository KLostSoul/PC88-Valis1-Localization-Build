# KANJI1 원천

`assignments.csv`는 음절·토큰·슬롯·ROM 오프셋 표입니다. 각 글리프의 16×16 1bpp 원천 TXT는 `source/kanji/`에 있습니다.

빌더는 문자 코드에서 슬롯을 계산하지 않습니다. 표에 적힌 `slot`과 `rom_offset`을 검증하고, 가리키는 TXT를 정확히 32바이트로 직렬화합니다.
