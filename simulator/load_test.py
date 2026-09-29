"""터미널에서 시나리오를 실행하고 결과를 출력한다. run.py 로 서버를 먼저 띄워 두어야 한다.

    python -m simulator.load_test            # 시나리오 목록
    python -m simulator.load_test rush       # 시나리오 실행
"""
import argparse
import sys
import time

import httpx

from common.config import gateway_base_url, load_config


def main():
    parser = argparse.ArgumentParser(description="게이트웨이 부하 시연")
    parser.add_argument("scenario", nargs="?", help="시나리오 ID")
    args = parser.parse_args()

    cfg = load_config()
    client = httpx.Client(base_url=gateway_base_url(cfg), headers={"X-Admin-Key": cfg["admin_key"]}, timeout=10)
    try:
        scenarios = client.get("/admin/scenarios").json()
    except httpx.HTTPError:
        sys.exit("게이트웨이에 연결할 수 없습니다. 먼저 `python run.py` 를 실행하세요.")

    if not args.scenario:
        print("사용 가능한 시나리오:")
        for s in scenarios:
            print(f"  {s['id']:<8} {s['title']} - {s['summary']}")
        return

    resp = client.post("/admin/simulate", json={"scenario": args.scenario})
    if resp.status_code != 200:
        sys.exit(resp.json().get("error", {}).get("message", resp.text))

    snap = {}
    while True:
        snap = client.get("/admin/simulation").json()
        done = sum(lane["done"] for lane in snap["lanes"].values())
        print(f"\r[{snap['title']}] 진행 {done}/{snap['total'] * 2}  경과 {snap['elapsed']}초   ", end="", flush=True)
        if snap["status"] == "done":
            break
        time.sleep(0.5)
    print("\n")

    rows = [("", "직접 호출", "게이트웨이")]
    d, g = snap["lanes"]["direct"], snap["lanes"]["gateway"]
    rows.append(("성공률", f"{d['success_rate']}%", f"{g['success_rate']}%"))
    rows.append(("성공 / 실패", f"{d['success']} / {d['failed']}", f"{g['success']} / {g['failed']}"))
    if d["platform"] and g["platform"]:
        rows.append(("플랫폼 호출 수", str(d["platform"]["calls"]), str(g["platform"]["calls"])))
        rows.append(("플랫폼 거절(429)", str(d["platform"]["rejected"]), str(g["platform"]["rejected"])))
        rows.append(("과금액", f"{d['platform']['billed']:,}원", f"{g['platform']['billed']:,}원"))
    rows.append(("평균 응답", f"{d['avg_ms']}ms", f"{g['avg_ms']}ms"))
    rows.append(("캐시·병합 응답", str(d["cached"]), str(g["cached"])))
    rows.append(("캐시로 아낀 비용", f"{d['saved_krw']:,}원", f"{g['saved_krw']:,}원"))
    for label, a, b in rows:
        print(f"  {label:<14}{a:>14}{b:>14}")
    if snap.get("focus"):
        f = snap["focus"]
        print(f"\n  [{f['label']} {f['name']}]")
        for lane, name in (("direct", "직접 호출"), ("gateway", "게이트웨이")):
            u, o = f[lane]["user"], f[lane]["others"]
            print(f"  {name}: {f['label']} 성공 {u['success']}/{u['total']}, 다른 직원 성공 {o['success']}/{o['total']}")
    print()
    for lane, name in (("direct", "직접 호출"), ("gateway", "게이트웨이")):
        if snap["lanes"][lane]["errors"]:
            print(f"  {name} 실패 사유: {snap['lanes'][lane]['errors']}")
    if snap.get("error"):
        print(f"  오류: {snap['error']}")


if __name__ == "__main__":
    main()
