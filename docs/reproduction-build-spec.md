# 재현 빌드 명세

## 목적

원본 Disk A D88과 원본 KANJI1 ROM을 입력으로 받아 검토된 직접 바이트 표를 적용하고, 파일 구조와 최종 해시를 검증합니다.

## 입력과 출력

- 입력: 사용자가 제공한 원본 D88과 KANJI1 ROM
- 출력: 원본 컨테이너를 보존한 재현 D88과 수정된 KANJI1 ROM
- 결과 대조: 완료본·IPS·추출 이미지와 결과를 비교합니다.

원본 D88은 `source/media/d88-layout.json`, 원본 KANJI1 ROM은 `source/media/kanji1-layout.json`의 레이아웃을 기준으로 확인합니다.

## 적용 규칙

1. 원본 파일 크기와 해시를 확인합니다.
2. 모든 직접 수정 행의 old 값이 원본 위치와 일치하는지 확인합니다.
3. 섹터 헤더와 payload가 아닌 영역은 쓰지 않습니다.
4. 중복·겹침·충돌을 거부합니다.
5. 출력 파일을 재파싱하고 컴포넌트별 변경 집합과 최종 해시를 확인합니다.

## 구성

이벤트 1~6, 게임오버, 엔딩 24개 세그먼트, 로고, ERROR 07, 제어 토큰, KANJI1 글리프와 직접 기록기가 각각 명시된 원천표를 사용합니다.

## 명령

```text
PYTHONPATH=. python -m tools.valis_rebuild source-lint
PYTHONPATH=. python -m tools.valis_rebuild text-lint
PYTHONPATH=. python -m tools.valis_rebuild build --d88 /path/to/original.d88 --rom /path/to/KANJI1.ROM
PYTHONPATH=. python -m tools.valis_rebuild verify --d88 "build/reproduction/d88/valis_disk_a(K).d88" --rom "build/reproduction/kanji/KANJI1(K).ROM"
```
