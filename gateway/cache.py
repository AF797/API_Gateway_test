"""응답 캐시 + 요청 병합.

- 캐시     : 같은 요청의 결과가 유효 시간 안에 있으면 플랫폼을 호출하지 않는다.
- 요청 병합 : 같은 요청이 이미 처리 중이면 새로 호출하지 않고 그 결과를 함께 기다린다.
운영 환경에서는 Redis 로 바꾸면 서버 여러 대가 캐시를 공유할 수 있다.
"""
import asyncio
import time


class ResponseCache:
    def __init__(self):
        self.store: dict[str, tuple[float, object]] = {}
        self.inflight: dict[str, asyncio.Future] = {}

    def get(self, key: str):
        item = self.store.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            del self.store[key]
            return None
        return value

    async def get_or_fetch(self, key: str, ttl: float, coalesce: bool, fetch):
        """(결과, 출처) 반환. 출처는 'cache' | 'coalesced' | 'origin'."""
        if ttl > 0:
            hit = self.get(key)
            if hit is not None:
                return hit, "cache"
        if coalesce and key in self.inflight:
            return await asyncio.shield(self.inflight[key]), "coalesced"

        future = asyncio.get_running_loop().create_future() if coalesce else None
        if future:
            self.inflight[key] = future
        try:
            result = await fetch()
        except Exception as exc:
            if future:
                future.set_exception(exc)
                future.exception()  # 기다리는 쪽이 없을 때 경고가 뜨지 않도록 '확인됨' 처리
            raise
        except BaseException:  # 요청이 취소된 경우
            if future:
                future.cancel()
            raise
        else:
            if ttl > 0:
                self.store[key] = (time.monotonic() + ttl, result)
            if future:
                future.set_result(result)
            return result, "origin"
        finally:
            if future:
                self.inflight.pop(key, None)
