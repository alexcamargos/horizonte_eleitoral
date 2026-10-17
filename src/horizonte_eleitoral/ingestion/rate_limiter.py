"""Limitador assincrono de requisicoes e concorrencia para o cliente TSE."""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Controlador de taxa de chamadas por segundo (token bucket) e concorrencia maxima."""

    def __init__(self, max_rate: float, max_concurrency: int) -> None:
        """Inicializa o limitador com taxa por segundo e teto de concorrencia.

        Args:
            max_rate: Numero maximo de requisicoes permitidas por segundo.
            max_concurrency: Numero maximo de conexoes concorrentes ativas.

        Returns:
            None.

        Raises:
            ValueError: Se max_rate ou max_concurrency forem menores ou iguais a zero.
        """
        if max_rate <= 0:
            raise ValueError("max_rate deve ser maior que zero.")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency deve ser maior que zero.")

        self._max_rate = float(max_rate)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._tokens = float(max_rate)
        self._last_time = time.monotonic()

    async def acquire(self) -> None:
        """Aguarda autorizacao de token e vaga de concorrencia antes de disparar requisicao.

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        await self._semaphore.acquire()
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_time
            self._last_time = now
            self._tokens = min(self._max_rate, self._tokens + elapsed * self._max_rate)

            if self._tokens < 1.0:
                needed = 1.0 - self._tokens
                wait_time = needed / self._max_rate
                await asyncio.sleep(wait_time)
                self._tokens = 0.0
                self._last_time = time.monotonic()
            else:
                self._tokens -= 1.0

    def release(self) -> None:
        """Libera a vaga de concorrencia quando a requisicao termina.

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        self._semaphore.release()
