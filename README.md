# DuoRoster · 두 사람 근무표

두 직원의 월별 근무표를 만들고 직접 수정하는 윈도우 데스크톱 앱입니다. 계산은 OR-Tools로 PC 안에서 실행하며, ChatGPT·Excel·Python을 별도로 설치할 필요가 없습니다. Excel은 내보낸 파일을 열 때만 필요합니다.

## 사용

GitHub Releases에서 Windows ZIP을 받아 압축을 푼 뒤 `DuoRoster/설치.cmd`를 실행하세요. 사용자 프로그램 폴더에 복사하고 바탕화면에 `두 사람 근무표` 아이콘을 만듭니다. 관리자 권한은 필요하지 않습니다. 압축을 푼 폴더의 `DuoRoster.exe`로 바로 실행할 수도 있습니다.

이름 설정, 휴무 지정, 근무표 만들기, 변경내역 확인, 엑셀/PDF 저장은 [사용 설명서](USER_GUIDE.md)를 참고하세요.

이름·휴무·계획·확정 실적은 `%APPDATA%/DuoRoster`에만 저장됩니다. GitHub로 전송하지 않습니다. 앱 실행 시 새 버전 정보만 확인하며, 사용자가 업데이트를 선택하면 GitHub Releases의 파일을 내려받습니다.

## 개발

Windows와 Python 3.14를 사용합니다.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-build.txt
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python main.py
```

원래 사용자 기록과 분리해서 시험하려면 `main.py --data-dir .local/test-profile`로 실행하세요. 저장 데이터, 출력물, 화면 캡처, 인증정보는 커밋하지 않습니다.

## 업데이트 배포

1. 코드를 수정하고 테스트합니다. 일반 push는 테스트만 실행합니다.
2. `duoroster/__init__.py`의 버전을 올립니다.
3. 변경 내용을 커밋하고 `v0.1.1`처럼 같은 버전의 태그를 push합니다. GitHub 웹에서는 Actions의 `Test and release Windows app`에서 `Run workflow`를 누르고 `release_tag`에 같은 버전을 입력할 수도 있습니다.
4. GitHub Actions가 테스트, Windows 빌드, 패키지 실행 확인을 거쳐 정식 Release를 만듭니다.
5. 사용자 앱은 시작 시 또는 `업데이트 확인`에서 새 정식 버전을 찾습니다. 사용자가 적용을 선택하면 기록 저장 후 앱을 교체하고 다시 실행합니다.

태그나 테스트가 실패하면 새 버전을 배포하지 않습니다. 배포 전 실행 중인 프로그램 폴더를 별도 보관하며, 근무 기록 폴더는 교체하지 않습니다. GitHub가 제공하는 SHA-256 값과 내려받은 파일을 비교하고 압축 경로를 검사합니다. 현재 앱 버전보다 높은 정식 버전만 제안합니다.

로컬 빌드는 `python tools/build.py`로 실행합니다. `release/`에 Windows ZIP과 체크섬 파일이 생깁니다.

업데이트 후 문제가 생기면 앱의 파일 메뉴에서 기록 백업을 복원할 수 있습니다. 이전 실행 파일은 설치 폴더 옆 `DuoRoster.previous-*`에 남습니다. 실행 파일 복구와 근무 기록 복구는 별개입니다.

## 규칙

필수 조건은 한 명씩 D/E 또는 MD/OFF, 주말·공휴일 단독 MD, 공휴일이 아닌 수요일 2인 근무, E 다음날 E/OFF, 최대 5일 연속근무, 지정한 월 휴무 일수, 월별 D/E 차이 최대 3일입니다.

기본 휴무는 `MAX(8, 주말·공휴일의 중복 없는 날짜 수 - 2)`일이며, 월별로 추가 휴무를 지정할 수 있습니다. 평일 OFF 후 D 복귀는 가장 낮은 선호이며 필요하면 E/MD로 복귀할 수 있습니다. 지정한 고정 근무는 자동 계산이 바꾸지 않습니다.

연간 균형에는 사용자가 실제 근무로 확정한 이전 달만 반영합니다. 전월 말 5일 기록이 없으면 월초 검사 미완료를 표시합니다. 다음 달 계획이 이미 있으면 두 달을 함께 계산할 수 있습니다.
