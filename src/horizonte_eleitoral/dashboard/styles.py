"""Estilos CSS customizados para replicar e aprimorar a identidade visual do projeto."""

from __future__ import annotations


def get_custom_css() -> str:
    """Gera a folha de estilo CSS customizada para o dashboard Streamlit.

    Implementa suporte a modo claro e escuro, cartoes responsivos, barras de probabilidade,
    ajustes finos de tipografia editorial e adaptabilidade para telas mobile.

    Args:
        None.

    Returns:
        String contendo a tag <style> com regras CSS completas e testadas.

    Raises:
        None.
    """
    return """
<style>
/* Variaveis e temas de cor */
:root {
  --s-PT: #e34948;
  --s-PL: #2a78d6;
  --s-OUTROS: #8a8983;
  --fundo-card: rgba(255, 255, 255, 0.95);
  --borda-card: #e6e5e1;
  --texto-card: #0b0b0b;
  --texto-mut: #64748b;
  --bg-suave: #f8fafc;
}

@media (prefers-color-scheme: dark) {
  :root {
    --fundo-card: rgba(26, 26, 25, 0.95);
    --borda-card: #2c2c2a;
    --texto-card: #ffffff;
    --texto-mut: #94a3b8;
    --bg-suave: #1e1e1e;
  }
}

/* Cabecalho Editorial */
.editorial-sobretitulo {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--texto-mut);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 2px;
}

.editorial-titulo {
  font-size: clamp(1.6rem, 3.0vw, 2.3rem);
  font-weight: 750;
  line-height: 1.15;
  margin: 2px 0 6px 0;
  letter-spacing: -0.02em;
}

.editorial-autoria {
  font-size: 0.88rem;
  color: var(--texto-mut);
  margin-bottom: 12px;
}

.editorial-status-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 0.95rem;
  margin-bottom: 14px;
}

.selo-alerta {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  background-color: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.selo-estavel {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  background-color: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.banner-aviso {
  background-color: var(--bg-suave);
  border-left: 4px solid #3b82f6;
  padding: 10px 14px;
  border-radius: 4px;
  font-size: 0.86rem;
  color: var(--texto-card);
  margin-bottom: 18px;
  line-height: 1.45;
}

.mobile-sidebar-hint {
  display: none;
}

@media (max-width: 768px) {
  .editorial-titulo {
    font-size: clamp(1.35rem, 5vw, 1.75rem);
    line-height: 1.2;
  }
  .mobile-sidebar-hint {
    display: block;
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.82rem;
    color: #1e40af;
    margin-bottom: 14px;
  }
}

/* Cartoes de Candidatos */
.cartao-candidato {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 12px;
  padding: 16px 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  margin-bottom: 12px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.cartao-candidato:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.06);
}

.cartao-candidato.cartao-lider {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.12);
}

.cartao-cabecalho {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.98rem;
  font-weight: 600;
}

.chave-cor {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  display: inline-block;
  flex-shrink: 0;
}

.chave-PT { background-color: var(--s-PT); }
.chave-PL { background-color: var(--s-PL); }
.chave-OUTROS { background-color: var(--s-OUTROS); }

.cartao-partido {
  color: var(--texto-mut);
  font-size: 0.85rem;
  font-weight: 500;
}

.cartao-badge-lider {
  margin-left: auto;
  font-size: 0.70rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 7px;
  border-radius: 999px;
  background-color: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.cartao-valor-destaque {
  font-size: clamp(2.1rem, 3.8vw, 2.9rem);
  font-weight: 750;
  line-height: 1.05;
  margin: 8px 0 2px 0;
  letter-spacing: -0.02em;
}

.cartao-rotulo {
  font-size: 0.80rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--texto-mut);
  margin-bottom: 6px;
}

.cartao-faixa {
  font-size: 0.80rem;
  font-weight: 600;
  color: #0f766e;
  background-color: #f0fdfa;
  padding: 2px 8px;
  border-radius: 6px;
  display: inline-block;
  margin-bottom: 6px;
  border: 1px solid #ccfbf1;
}

.cartao-apurado-container {
  border-top: 1px dashed var(--borda-card);
  padding-top: 8px;
  margin-top: 6px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.cartao-apurado-label {
  font-size: 0.82rem;
  color: var(--texto-mut);
}

.cartao-apurado-valor {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--texto-card);
}

.cartao-vies-nota {
  font-size: 0.72rem;
  color: var(--texto-mut);
  margin-top: 2px;
  line-height: 1.3;
}

/* Banner Estruturado de Probabilidade de 2o Turno */
.painel-p2t-container {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 12px;
  padding: 14px 18px;
  margin: 14px 0 20px 0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.painel-p2t-topo {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.painel-p2t-titulo {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--texto-card);
}

.painel-p2t-lado-direito {
  display: flex;
  align-items: center;
  gap: 10px;
}

.p2t-destaque {
  font-size: 1.25rem;
  font-weight: 750;
  color: #1e3a8a;
}

.p2t-badge {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 2px 8px;
  border-radius: 999px;
  background-color: #dbeafe;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}

.p2t-barra-trilha {
  width: 100%;
  height: 8px;
  background-color: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
  margin: 6px 0 6px 0;
}

.p2t-barra-preenchimento {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6 0%, #1d4ed8 100%);
  border-radius: 999px;
  transition: width 0.4s ease;
}

.painel-p2t-subtitulo {
  font-size: 0.80rem;
  color: var(--texto-mut);
  line-height: 1.35;
}

/* Legenda e Guia dos Graficos */
.grafico-guia-container {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 10px;
  padding: 14px 18px;
  margin: 8px 0 14px 0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.grafico-descricao {
  font-size: 0.88rem;
  line-height: 1.5;
  color: var(--texto-mut);
  margin-bottom: 10px;
}

.grafico-legenda-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  align-items: center;
  border-top: 1px solid var(--borda-card);
  padding-top: 10px;
}

.grafico-legenda-bloco {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.grafico-legenda-titulo {
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--texto-mut);
  margin-right: 2px;
}

.grafico-legenda-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.84rem;
  font-weight: 500;
}

.amostra-linha-solida {
  width: 20px;
  height: 3px;
  background-color: #475569;
  border-radius: 1px;
  display: inline-block;
}

.amostra-linha-tracejada {
  width: 20px;
  height: 0px;
  border-top: 2.5px dashed #475569;
  display: inline-block;
}

.amostra-faixa-ic {
  width: 16px;
  height: 12px;
  background-color: rgba(71, 85, 105, 0.28);
  border: 1px solid rgba(71, 85, 105, 0.50);
  border-radius: 2px;
  display: inline-block;
}

.amostra-linha-50 {
  width: 20px;
  height: 0px;
  border-top: 2px dotted #94a3b8;
  display: inline-block;
}

/* Ficha Tecnica em Grid */
.model-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 12px 0;
}

.model-card-box {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 8px;
  padding: 12px 14px;
}

.model-card-box-titulo {
  font-size: 0.88rem;
  font-weight: 700;
  margin-bottom: 4px;
  color: var(--texto-card);
}

.model-card-box-desc {
  font-size: 0.82rem;
  color: var(--texto-mut);
  line-height: 1.45;
}

/* Fallback do Modo Ao Vivo */
.api-offline-card {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 16px 20px;
  margin: 14px 0;
  line-height: 1.5;
}
</style>
"""
