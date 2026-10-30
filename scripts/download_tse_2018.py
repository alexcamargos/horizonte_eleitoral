"""Script utilitario para download direto dos dados oficiais de secoes eleitorais de 2018 do TSE."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from horizonte_eleitoral.config import get_raw_data_dir

TSE_2018_SECTIONS_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2018_BR.zip"
)


def download_tse_2018_file(
    target_path: Path,
    url: str = TSE_2018_SECTIONS_URL,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Baixa o arquivo zip de votacao por secao de 2018 diretamente do CDN oficial do TSE.

    Args:
        target_path: Caminho de destino para salvar o arquivo ZIP.
        url: URL oficial do arquivo no repositorio do TSE.
        chunk_size: Tamanho do bloco em bytes para leitura em streaming.

    Returns:
        Caminho final do arquivo baixado.

    Raises:
        RuntimeError: Se o download falhar ou o servidor retornar status diferente de 200.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and target_path.stat().st_size > 200 * 1024 * 1024:
        mb_size = target_path.stat().st_size / 1024 / 1024
        print(f"Arquivo 2018 ja existe em {target_path} ({mb_size:.2f} MB).")
        return target_path

    temp_path = target_path.with_suffix(".tmp")
    print(f"Iniciando download do TSE de: {url}")
    t0 = time.time()

    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        if response.status_code != 200:
            raise RuntimeError(f"Erro ao baixar do TSE. Status HTTP: {response.status_code}")

        total_bytes = int(response.headers.get("content-length", 0))
        downloaded = 0
        last_print = 0.0

        with open(temp_path, "wb") as out_f:
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                out_f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_print > 2.0:
                    last_print = now
                    pct = (downloaded / total_bytes * 100.0) if total_bytes > 0 else 0.0
                    mb = downloaded / (1024 * 1024)
                    speed = mb / max(0.1, now - t0)
                    print(f"Progresso: {mb:.1f} MB ({pct:.1f}%) a {speed:.2f} MB/s...")

    temp_path.replace(target_path)
    total_time = time.time() - t0
    final_mb = target_path.stat().st_size / (1024 * 1024)
    print(f"Download concluido: {final_mb:.1f} MB em {total_time:.2f}s ({target_path}).")
    return target_path


def main() -> None:
    """Ponto de entrada do script de download de dados de 2018."""
    target = get_raw_data_dir() / "votacao_secao_2018_BR.zip"
    download_tse_2018_file(target)


if __name__ == "__main__":
    main()
