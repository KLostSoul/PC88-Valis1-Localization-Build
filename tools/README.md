# 빌드 도구

저장소 루트에서 `python -m tools.valis_rebuild`을 실행합니다. Python 표준 라이브러리만 사용합니다.

```console
python -m tools.valis_rebuild source-lint
python -m tools.valis_rebuild text-lint
python -m tools.valis_rebuild build --d88 import --rom import
python -m tools.valis_rebuild verify --d88 output --rom output
```

`build`는 기준 크기와 SHA-256으로 `import/`에서 원본을 찾습니다. 파일명은 선택 기준에 포함되지 않습니다. `output/`에 한글 적용 D88, KANJI1 ROM, 각각의 IPS 패치를 저장합니다. `build-d88`과 `build-rom`은 한쪽 결과만 생성하며, `--out`으로 출력 폴더를 지정할 수 있습니다. `verify`는 D88 구조, 현재 소스와의 일치, 출력 폴더의 IPS 재적용 결과를 확인합니다.

## 모듈

| 파일 | 역할 |
| --- | --- |
| `valis_rebuild/cli.py` | 명령행 옵션, 원본 탐색, 검사·비교 명령 처리 |
| `valis_rebuild/pipeline.py` | 원본 검증, 패치 구성요소 실행, ROM 생성과 빌드 보고서 작성 |
| `valis_rebuild/d88.py` | D88 트랙·섹터 구조 분석과 payload 기록 |
| `valis_rebuild/serializer.py`, `gameover.py` | 검토된 바이트 표와 게임오버 자료 적용 |
| `valis_rebuild/logo.py` | `source/GFX/` PNG 인코딩과 D88 로고 영역 기록 |
| `valis_rebuild/kanji.py` | 글리프 배정표를 사용해 KANJI1 ROM 생성 |
| `valis_rebuild/ips.py` | 원본과 결과의 차이로 IPS 생성, 재적용 검증 |
| `valis_rebuild/outputs.py` | 결과 파일 묶음 저장과 오류 발생 시 이전 파일 복구 |
| `valis_rebuild/source_gate.py`, `text_sources.py` | 빌드 소스와 번역·토큰 데이터 검사 |
| `valis_rebuild/codec.py`, `errors.py` | 게임 문자 바이트 처리와 빌드 오류 정의 |

패치 데이터와 편집 입력을 수정할 때는 [직접 바이너리 재현 빌드 안내서](../docs/direct-binary-build.md)를 참고하세요.
