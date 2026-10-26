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
/* Variaveis e temas de cor no padrao editorial */
:root {
  --s-PT: #e34948;
  --s-PL: #2a78d6;
  --s-OUTROS: #8a8983;
  --fundo-card: #ffffff;
  --borda-card: #e2e8f0;
  --texto-card: #0f172a;
  --texto-mut: #64748b;
  --bg-suave: #f8fafc;
  --badge-bg-pt: #fee2e2;
  --badge-fg-pt: #991b1b;
  --badge-bg-pl: #dbeafe;
  --badge-fg-pl: #1e40af;
  --badge-bg-lider: #fef3c7;
  --badge-fg-lider: #92400e;
  --box-win-lider-bg: #dcfce7;
  --box-win-lider-fg: #166534;
  --box-win-sec-bg: #f1f5f9;
  --box-win-sec-fg: #475569;
  --box-faixa-bg: #f0fdfa;
  --box-faixa-fg: #0f766e;
  --box-faixa-border: #ccfbf1;
  --p2t-destaque-fg: #1e3a8a;
  --p2t-badge-bg: #dbeafe;
  --p2t-badge-fg: #1e40af;
  --p2t-badge-border: #bfdbfe;
  --kpi-top-gabarito: #64748b;
}

@media (prefers-color-scheme: dark) {
  :root {
    --fundo-card: #181d28;
    --borda-card: #283347;
    --texto-card: #f8fafc;
    --texto-mut: #94a3b8;
    --bg-suave: #0f172a;
    --badge-bg-pt: rgba(227, 73, 72, 0.18);
    --badge-fg-pt: #fca5a5;
    --badge-bg-pl: rgba(42, 120, 214, 0.18);
    --badge-fg-pl: #93c5fd;
    --badge-bg-lider: rgba(245, 158, 11, 0.2);
    --badge-fg-lider: #fde047;
    --box-win-lider-bg: rgba(34, 197, 94, 0.16);
    --box-win-lider-fg: #86efac;
    --box-win-sec-bg: rgba(148, 163, 184, 0.12);
    --box-win-sec-fg: #cbd5e1;
    --box-faixa-bg: rgba(20, 184, 166, 0.15);
    --box-faixa-fg: #5eead4;
    --box-faixa-border: rgba(20, 184, 166, 0.35);
    --p2t-destaque-fg: #60a5fa;
    --p2t-badge-bg: rgba(59, 130, 246, 0.2);
    --p2t-badge-fg: #93c5fd;
    --p2t-badge-border: rgba(59, 130, 246, 0.4);
    --kpi-top-gabarito: #94a3b8;
  }
}

/* Suporte complementar ao tema escuro nativo do Streamlit */
[data-testid="stAppViewContainer"] {
  --fundo-card: #181d28;
  --borda-card: #283347;
  --texto-card: #f8fafc;
  --texto-mut: #94a3b8;
  --bg-suave: #0f172a;
  --badge-bg-pt: rgba(227, 73, 72, 0.18);
  --badge-fg-pt: #fca5a5;
  --badge-bg-pl: rgba(42, 120, 214, 0.18);
  --badge-fg-pl: #93c5fd;
  --badge-bg-lider: rgba(245, 158, 11, 0.2);
  --badge-fg-lider: #fde047;
  --box-win-lider-bg: rgba(34, 197, 94, 0.16);
  --box-win-lider-fg: #86efac;
  --box-win-sec-bg: rgba(148, 163, 184, 0.12);
  --box-win-sec-fg: #cbd5e1;
  --box-faixa-bg: rgba(20, 184, 166, 0.15);
  --box-faixa-fg: #5eead4;
  --box-faixa-border: rgba(20, 184, 166, 0.35);
  --p2t-destaque-fg: #60a5fa;
  --p2t-badge-bg: rgba(59, 130, 246, 0.2);
  --p2t-badge-fg: #93c5fd;
  --p2t-badge-border: rgba(59, 130, 246, 0.4);
  --kpi-top-gabarito: #94a3b8;
}

/* Badge editorial do Modelo na Barra Lateral */
.sidebar-model-badge {
  background: var(--bg-suave);
  border: 1px solid var(--borda-card);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 6px 0 16px 0;
}

.model-badge-header {
  font-size: 0.68rem;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--texto-mut);
  margin-bottom: 2px;
}

.model-badge-name {
  font-size: 0.90rem;
  font-weight: 700;
  color: var(--texto-card);
}

.model-badge-meta {
  font-size: 0.74rem;
  color: var(--texto-mut);
  margin-top: 2px;
  line-height: 1.35;
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
  background-color: var(--badge-bg-lider);
  color: var(--badge-fg-lider);
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.selo-estavel {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  background-color: var(--box-win-lider-bg);
  color: var(--box-win-lider-fg);
  border: 1px solid rgba(34, 197, 94, 0.35);
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
    background-color: var(--bg-suave);
    border: 1px solid var(--borda-card);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.82rem;
    color: var(--texto-card);
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
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
}

.cartao-candidato.cartao-lider {
  border-color: #3b82f6;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
}

.cartao-cabecalho {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--texto-card);
}

.chave-cor {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
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
  background-color: var(--badge-bg-lider);
  color: var(--badge-fg-lider);
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.cartao-valor-destaque {
  font-size: clamp(2.1rem, 3.8vw, 2.9rem);
  font-weight: 750;
  line-height: 1.05;
  margin: 8px 0 2px 0;
  letter-spacing: -0.02em;
  color: var(--texto-card);
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
  color: var(--box-faixa-fg);
  background-color: var(--box-faixa-bg);
  padding: 2px 8px;
  border-radius: 6px;
  display: inline-block;
  margin-bottom: 6px;
  border: 1px solid var(--box-faixa-border);
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
  color: var(--p2t-destaque-fg);
}

.p2t-badge {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 2px 8px;
  border-radius: 999px;
  background-color: var(--p2t-badge-bg);
  color: var(--p2t-badge-fg);
  border: 1px solid var(--p2t-badge-border);
}

.p2t-barra-trilha {
  width: 100%;
  height: 8px;
  background-color: var(--borda-card);
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
  color: var(--texto-card);
}

.amostra-linha-solida {
  width: 20px;
  height: 3px;
  background-color: var(--texto-mut);
  border-radius: 1px;
  display: inline-block;
  vertical-align: middle;
}

.amostra-linha-tracejada {
  width: 20px;
  height: 0px;
  border-top: 2.5px dashed var(--texto-mut);
  display: inline-block;
  vertical-align: middle;
}

.amostra-faixa-ic {
  width: 16px;
  height: 12px;
  background-color: rgba(148, 163, 184, 0.28);
  border: 1px solid rgba(148, 163, 184, 0.50);
  border-radius: 2px;
  display: inline-block;
  vertical-align: middle;
}

.amostra-linha-50 {
  width: 20px;
  height: 0px;
  border-top: 2px dotted #94a3b8;
  display: inline-block;
  vertical-align: middle;
}

.amostra-linha-gabarito {
  width: 20px;
  height: 0px;
  border-top: 2px dotted #0d9488;
  display: inline-block;
  vertical-align: middle;
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
  background: var(--bg-suave);
  border: 1px solid var(--borda-card);
  border-radius: 10px;
  padding: 16px 20px;
  margin: 14px 0;
  line-height: 1.5;
  color: var(--texto-card);
}

/* Cartoes de Disputa Direta do 2o Turno */
.card-candidato {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  margin-bottom: 12px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.card-candidato:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
}

.card-candidato-pt {
  border-left: 5px solid var(--s-PT);
}

.card-candidato-pl {
  border-left: 5px solid var(--s-PL);
}

.card-cand-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.card-nome {
  font-size: 1.15rem;
  font-weight: 750;
  color: var(--texto-card);
}

.badge-partido {
  font-size: 0.76rem;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
  letter-spacing: 0.03em;
}

.badge-partido-pt {
  background: var(--badge-bg-pt);
  color: var(--badge-fg-pt);
  border: 1px solid rgba(227, 73, 72, 0.3);
}

.badge-partido-pl {
  background: var(--badge-bg-pl);
  color: var(--badge-fg-pl);
  border: 1px solid rgba(42, 120, 214, 0.3);
}

.card-projecao {
  font-size: clamp(2.1rem, 3.6vw, 2.85rem);
  font-weight: 800;
  line-height: 1.08;
  margin: 4px 0 4px 0;
  letter-spacing: -0.02em;
}

.card-projecao-pt {
  color: var(--s-PT);
}

.card-projecao-pl {
  color: var(--s-PL);
}

.card-faixa {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--box-faixa-fg);
  background-color: var(--box-faixa-bg);
  border: 1px solid var(--box-faixa-border);
  padding: 2px 8px;
  border-radius: 6px;
  display: inline-block;
  margin-bottom: 6px;
}

.card-apurado {
  font-size: 0.88rem;
  color: var(--texto-mut);
  border-top: 1px dashed var(--borda-card);
  padding-top: 8px;
  margin-top: 4px;
}

.chance-vitoria-box {
  margin-top: 10px;
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 0.84rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

.chance-vitoria-box.chance-lider {
  background: var(--box-win-lider-bg);
  color: var(--box-win-lider-fg);
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.chance-vitoria-box.chance-secundario {
  background: var(--box-win-sec-bg);
  color: var(--box-win-sec-fg);
  border: 1px solid var(--borda-card);
}

.chance-vitoria-box.chance-preliminar {
  background: var(--bg-suave);
  color: var(--texto-mut);
  border: 1px dashed var(--borda-card);
  font-size: 0.80rem;
}

/* Painel de Auditoria Retroativa do 2o Turno */
.kpi-validacao-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
  margin: 14px 0 18px 0;
}

.kpi-validacao-card {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 10px;
  padding: 13px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.kpi-validacao-label {
  font-size: 0.74rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--texto-mut);
  margin-bottom: 4px;
}

.kpi-validacao-valor {
  font-size: 1.32rem;
  font-weight: 800;
  color: var(--texto-card);
  line-height: 1.2;
}

.kpi-validacao-sub {
  font-size: 0.79rem;
  color: var(--texto-mut);
  margin-top: 4px;
  line-height: 1.35;
}

/* Caixa de Status de Sincronizacao com o TSE */
.status-box-container {
  background: var(--fundo-card);
  border: 1px solid var(--borda-card);
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.status-box-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.status-badge {
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 0.78rem;
  letter-spacing: 0.02em;
}

.status-badge-active {
  background: var(--box-win-lider-bg);
  color: var(--box-win-lider-fg);
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.status-badge-waiting {
  background: var(--badge-bg-lider);
  color: var(--badge-fg-lider);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.status-time {
  font-size: 0.85rem;
  color: var(--texto-mut);
}

.status-time strong {
  color: var(--texto-card);
}

.status-grid {
  display: flex;
  gap: 28px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.status-item {
  flex: 1;
  min-width: 200px;
}

.status-item-divider {
  border-left: 1px solid var(--borda-card);
  padding-left: 24px;
}

.status-lbl {
  font-size: 0.78rem;
  text-transform: uppercase;
  color: var(--texto-mut);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.status-val {
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--texto-card);
  margin-top: 2px;
}

.status-sub {
  font-size: 0.90rem;
  font-weight: 500;
  color: var(--texto-mut);
}

.status-msg {
  margin-top: 10px;
  font-size: 0.82rem;
  color: var(--texto-mut);
}
</style>
"""
