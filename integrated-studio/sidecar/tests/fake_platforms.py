"""화면 시험용: test_importers.py 의 가짜 Modrinth·CurseForge 서버를 고정 포트로 띄운다.
사용: python tests/fake_platforms.py 8765
앱은 INTEGRATED_STUDIO_MODRINTH_API=http://127.0.0.1:8765/mr, INTEGRATED_STUDIO_CURSEFORGE_API=http://127.0.0.1:8765/cf 로 띄운다.
"""
import http.server
import sys
import urllib.request

import test_importers as t

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
try:
    remote = urllib.request.urlopen(t.REMOTE_FILE, timeout=20).read()
except Exception:  # noqa: BLE001
    remote = None
t.Fake.base = f"http://127.0.0.1:{port}"
t.Fake.mrpack = t.make_mrpack(remote)
t.Fake.cf_zip = t.make_cf_zip()
print(f"fake platforms on {t.Fake.base}", flush=True)
http.server.ThreadingHTTPServer(("127.0.0.1", port), t.Fake).serve_forever()
