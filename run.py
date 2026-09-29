"""가상 플랫폼 서버와 통합 API 게이트웨이를 한 번에 실행한다.

    python run.py                  # 이 PC에서만 접속
    python run.py --host 0.0.0.0   # 같은 네트워크의 다른 PC에서도 접속
"""
import argparse
import asyncio
import contextlib
import socket

import uvicorn

from common.config import load_config


class _Server(uvicorn.Server):
    """서버 두 개를 한 프로세스에서 돌리므로 개별 시그널 처리는 끄고 Ctrl+C 는 run.py 가 처리한다."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield

    def install_signal_handlers(self):  # 구버전 uvicorn 호환
        pass


def busy_ports(host: str, ports: list[int]) -> list[int]:
    """이미 다른 프로그램(보통 먼저 띄워 둔 run.py)이 쓰고 있는 포트."""
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                busy.append(port)
    return busy


async def main(host: str):
    cfg = load_config()["server"]
    busy = busy_ports(host, [cfg["mock_port"], cfg["gateway_port"]])
    if busy:
        ports = ",".join(map(str, busy))
        print(f"""
  포트 {ports} 번을 이미 다른 프로그램이 쓰고 있어서 실행할 수 없습니다.
  대부분 run.py 가 이미 실행 중인 경우입니다.

  - 이미 켜져 있다면 그대로 http://localhost:{cfg['gateway_port']} 에 접속하면 됩니다.
  - 새로 켜려면 기존 창에서 Ctrl+C 로 끄거나, PowerShell 에서 아래 명령으로 끈 뒤 다시 실행하세요.
      Get-NetTCPConnection -LocalPort {ports} -State Listen | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}
  - 다른 포트를 쓰려면 config.yaml 의 server 항목을 바꾸세요.
""")
        return
    servers = [
        _Server(uvicorn.Config("mock_platforms.app:app", host=host, port=cfg["mock_port"], log_level="warning")),
        _Server(uvicorn.Config("gateway.app:app", host=host, port=cfg["gateway_port"], log_level="warning")),
    ]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    while not all(s.started for s in servers):
        if any(t.done() for t in tasks):  # 포트 충돌 등으로 시작 실패
            await asyncio.gather(*tasks)
            return
        await asyncio.sleep(0.1)

    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"""
  통합 API 게이트웨이 프로토타입이 실행되었습니다.

  대시보드     http://{shown}:{cfg['gateway_port']}/dashboard
  API 문서     http://{shown}:{cfg['gateway_port']}/docs
  가상 플랫폼  http://{shown}:{cfg['mock_port']}/docs

  종료하려면 Ctrl+C 를 누르세요.
""", flush=True)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="통합 API 게이트웨이 프로토타입 실행")
    parser.add_argument("--host", default=load_config()["server"]["host"])
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host))
    except KeyboardInterrupt:
        print("\n  종료합니다.")
