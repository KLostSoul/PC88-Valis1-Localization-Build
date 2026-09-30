# 테스트

저장소 루트에서 Python 표준 라이브러리의 `unittest`로 실행합니다.

```console
python -m unittest discover -s tests -v
```

## 테스트 파일

| 파일 | 검사 내용 |
| --- | --- |
| `test_source_gate.py` | 확정 소스 매니페스트와 빌드 가능 조건 |
| `test_source_components.py` | 번역·패치표 구조, 글리프 ROM, 원본 미디어 통합 빌드 |
| `test_d88_layout.py` | 원본 D88 트랙·섹터 배치 |
| `test_low_level.py` | 저수준 게임 바이트 디코딩·인코딩 |
| `test_ips.py` | IPS 레코드, 길이 경계, 재적용, 출력 저장 복구 |
| `test_build_contract.py` | 원본 보호, 입력 계약, 로고 편집, D88 매핑, 검증과 문서 참조 |
| `media_inputs.py` | 기준 크기와 SHA-256으로 테스트용 원본 미디어 찾기 |

통합 D88·ROM 검사는 기준 원본이 필요합니다. 기본 위치는 저장소의 `import/`입니다. 파일 이름은 해시 조회에 영향을 주지 않습니다. 다른 경로의 원본을 사용하려면 `VALIS_ORIGINAL_D88`, `VALIS_ORIGINAL_ROM` 환경 변수에 각각 경로를 지정할 수 있습니다. 원본이 없으면 해당 미디어를 사용하는 검사는 건너뜁니다.
