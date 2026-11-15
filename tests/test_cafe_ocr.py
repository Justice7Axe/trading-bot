"""☕ 카페 그림 OCR 종목 맞추기 시험 — 가짜 OCR 줄과 가짜 종목 이름표로 (윈도우 OCR·인터넷 없이)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from kiwoom_trading.common import cafe_universe as C   # noqa: E402

NAMES = {"가온칩스": "399720", "퀄리타스반도체": "432720", "한국콜마": "161890", "한국파마": "032300",
         "SV인베스트먼트": "289080", "삼현": "437730", "반도체": "999999", "에코캡": "128540",
         "LIG디펜스앤에어로스페이스": "079550", "KBI메탈": "024840", "KBI동양철관": "008970"}


def test_exact_close_alias_and_jamo():
    lines = ["반도체 관련주",                      # 괄호 숫자 없는 제목 줄은 안 봄 (같은 이름 종목이 있어도)
             "가온집스 (29.921%)",                  # 비슷함 0.75 → 가온칩스
             "퀄리타스반도제 (15.43%)",             # → 퀄리타스반도체
             "삼현 (8.7970",                         # 똑같음 (% 깨져도 괄호 뒤 숫자면 됨)
             "sv인베A트먼트 (7.95%)",               # 대소문자 무시 → SV인베스트먼트
             "한국를마 (7.44%)",                    # 자모로 보면 한국콜마가 한국파마보다 가까움 (콜마 ㅋㅗㄹ 의 받침 ㄹ 이 맞음)
             "에코컙 (13.94%)",                     # 자모 하나 틀림 (ㅐ→ㅓ) → 에코캡
             "LIG D&A (9.73%)",                     # 카페 줄임 이름 → LIG디펜스앤에어로스페이스
             "KBIOII# (24.667。)"]                   # 너무 깨짐 → 못 맞춤
    found, miss = C.names_from_ocr(lines, NAMES)
    assert found == {"399720": "가온칩스", "432720": "퀄리타스반도체", "437730": "삼현", "289080": "SV인베스트먼트",
                     "161890": "한국콜마", "128540": "에코캡", "079550": "LIG디펜스앤에어로스페이스"}
    assert miss == ["KBIOII#"]


def test_tie_is_dropped():
    found, miss = C.names_from_ocr(["KBI메털 (24.6%)"], {"KBI메탈A": "1", "KBI메탈B": "2"})   # 둘이 같은 점수 → 버림
    assert not found and miss == ["KBI메털"]


def test_refresh_uses_ocr_when_body_is_image():
    import tempfile
    from datetime import datetime
    body = '<div><img src="https://x/a.png"></div>'
    arts = [{"id": 1, "subject": "11월 13일 특징테마", "writer": "", "ts": ""}]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cafe.json")
        u = C.refresh(datetime(2026, 11, 16, 7, 50), path, names=NAMES, fetch_list_fn=lambda: arts,
                      fetch_body_fn=lambda aid, ck: body, cookie={"NID_AUT": "a", "NID_SES": "b"},
                      read_images_fn=lambda imgs, names, ck: C.names_from_ocr(["가온집스 (29.9%)", "삼현 (8.8%)"], names))
        assert u.active and set(u.codes) == {"399720", "437730"}
        assert u.articles[0]["ocr"] is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
