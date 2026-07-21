import json
import os
from datetime import date, datetime

import pandas as pd
import streamlit as st
from fpdf import FPDF

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
st.set_page_config(page_title="Gerador de Orçamentos", page_icon="📄", layout="wide")

EMPRESAS_FILE = "empresas.json"
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ------------------------------------------------------------------
# PERSISTÊNCIA DE EMPRESAS REPRESENTADAS (nome + CNPJ)
# ------------------------------------------------------------------
def carregar_empresas():
    if os.path.exists(EMPRESAS_FILE):
        try:
            with open(EMPRESAS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def salvar_empresas(empresas):
    with open(EMPRESAS_FILE, "w", encoding="utf-8") as f:
        json.dump(empresas, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def brl(v):
    """Formata número no padrão brasileiro: 1.234,56"""
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def horas_fmt(h):
    return f"{h:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " h"


def _s(txt):
    """Sanitiza texto para as fontes core do fpdf (latin-1). Mantém acentos,
    troca caracteres Unicode não suportados (travessão, reticências, aspas)."""
    if txt is None:
        return ""
    txt = str(txt)
    repl = {"—": "-", "–": "-", "…": "...", "’": "'", "‘": "'",
            "“": '"', "”": '"', "•": "-"}
    for k, v in repl.items():
        txt = txt.replace(k, v)
    return txt.encode("latin-1", "replace").decode("latin-1")


# ------------------------------------------------------------------
# MOTOR DE CÁLCULO
# ------------------------------------------------------------------
def calcular_linha(row, valor_hora, jornada, pct_extra, pct_dom_fer):
    """Retorna dict com horas normais, extras, dom/feriado e valor da linha."""
    dt = row["Data"]
    horas = float(row["Horas"] or 0)
    feriado = bool(row["Feriado"])

    if isinstance(dt, str):
        dt = datetime.strptime(dt, "%Y-%m-%d").date()

    is_domingo = dt.weekday() == 6
    especial = is_domingo or feriado

    h_normal = h_extra = h_domfer = 0.0
    valor = 0.0

    if especial:
        h_domfer = horas
        valor = horas * valor_hora * (1 + pct_dom_fer / 100)
        tipo = "Domingo/Feriado"
    else:
        h_normal = min(horas, jornada)
        h_extra = max(0.0, horas - jornada)
        valor = h_normal * valor_hora + h_extra * valor_hora * (1 + pct_extra / 100)
        tipo = "Dia útil"

    return {
        "tipo": tipo,
        "dia_semana": DIAS_SEMANA[dt.weekday()],
        "h_normal": h_normal,
        "h_extra": h_extra,
        "h_domfer": h_domfer,
        "valor": valor,
    }


# ------------------------------------------------------------------
# GERAÇÃO DO PDF
# ------------------------------------------------------------------
class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, "ORÇAMENTO DE SERVIÇOS", ln=True, align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Gerado em {datetime.now():%d/%m/%Y %H:%M} - Página {self.page_no()}",
                  align="C")


def gerar_pdf(dados):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ---- Prestador / empresa representada ----
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, "PRESTADOR / EMPRESA REPRESENTADA", ln=True, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"Empresa: {dados['empresa_nome']}"), ln=True)
    pdf.cell(0, 6, _s(f"CNPJ: {dados['empresa_cnpj']}"), ln=True)
    pdf.ln(3)

    # ---- Contratante ----
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "CONTRATANTE", ln=True, fill=True)
    pdf.set_font("Helvetica", "", 10)
    if dados["cliente_nome"]:
        pdf.cell(0, 6, _s(f"Empresa: {dados['cliente_nome']}"), ln=True)
    if dados["email1"]:
        pdf.cell(0, 6, _s(f"E-mail 1: {dados['email1']}"), ln=True)
    if dados["email2"]:
        pdf.cell(0, 6, _s(f"E-mail 2: {dados['email2']}"), ln=True)
    pdf.ln(3)

    # ---- Orçamento nº e data ----
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Orçamento nº: {dados['numero']}    Data: {dados['data']:%d/%m/%Y}", ln=True)
    pdf.ln(2)

    # ---- Corpo: fechado ou por horas ----
    if dados["modo"] == "fechado":
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "SERVIÇO (TRABALHO FECHADO)", ln=True, fill=True)
        pdf.set_font("Helvetica", "", 10)
        if dados["descricao_fechado"]:
            pdf.multi_cell(0, 6, _s(f"Descrição: {dados['descricao_fechado']}"))
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Valor do serviço: {brl(dados['valor_fechado'])}", ln=True)
    else:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "DETALHAMENTO DE HORAS", ln=True, fill=True)

        # Cabeçalho da tabela
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(220, 220, 220)
        larguras = [22, 20, 46, 16, 16, 16, 24, 20]
        cab = ["Data", "Dia", "Descrição", "Normal", "Extra", "D/F", "Total h", "Valor"]
        for w, c in zip(larguras, cab):
            pdf.cell(w, 7, c, border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for l in dados["linhas"]:
            total_h = l["h_normal"] + l["h_extra"] + l["h_domfer"]
            desc = (l["descricao"][:26] + "...") if len(l["descricao"]) > 27 else l["descricao"]
            valores = [
                l["data"].strftime("%d/%m/%y"),
                l["dia_semana"][:3],
                _s(desc),
                f"{l['h_normal']:.1f}",
                f"{l['h_extra']:.1f}",
                f"{l['h_domfer']:.1f}",
                f"{total_h:.1f}",
                brl(l["valor"]).replace("R$ ", ""),
            ]
            aligns = ["C", "C", "L", "R", "R", "R", "R", "R"]
            for w, v, a in zip(larguras, valores, aligns):
                pdf.cell(w, 6, v, border=1, align=a)
            pdf.ln()

        # Resumo
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Valor da hora normal: {brl(dados['valor_hora'])}", ln=True)
        pdf.cell(0, 6, f"Jornada normal/dia: {dados['jornada']:.1f} h  |  "
                       f"Hora extra: +{dados['pct_extra']:.0f}%  |  "
                       f"Domingo/Feriado: +{dados['pct_dom_fer']:.0f}%", ln=True)
        pdf.ln(1)
        pdf.cell(0, 6, f"Total horas normais: {horas_fmt(dados['tot_normal'])}", ln=True)
        pdf.cell(0, 6, f"Total horas extras: {horas_fmt(dados['tot_extra'])}", ln=True)
        pdf.cell(0, 6, f"Total horas domingo/feriado: {horas_fmt(dados['tot_domfer'])}", ln=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_fill_color(230, 240, 255)
        pdf.cell(0, 10, f"VALOR TOTAL: {brl(dados['total'])}", ln=True, fill=True, align="R")

    # ---- Observações ----
    if dados.get("observacoes"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Observações:", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _s(dados["observacoes"]))

    return bytes(pdf.output())


# ==================================================================
# INTERFACE
# ==================================================================
st.title("📄 Gerador de Orçamentos e Horas Trabalhadas")

if "empresas" not in st.session_state:
    st.session_state.empresas = carregar_empresas()

# ---------------- SIDEBAR: parâmetros de cálculo -------------------
with st.sidebar:
    st.header("⚙️ Parâmetros")
    valor_hora = st.number_input("Valor da hora normal (R$)", min_value=0.0, value=50.0, step=5.0)
    jornada = st.number_input("Jornada normal por dia (h)", min_value=1.0, value=8.0, step=0.5,
                              help="Horas acima disso, em dia útil, contam como hora extra.")
    pct_extra = st.number_input("Acréscimo hora extra (%)", min_value=0.0, value=50.0, step=5.0)
    pct_dom_fer = st.number_input("Acréscimo domingo/feriado (%)", min_value=0.0, value=100.0, step=5.0)
    st.caption("Sábado é tratado como dia útil (com hora extra acima da jornada). "
               "Domingo é detectado automaticamente pela data.")

# ---------------- EMPRESA REPRESENTADA -----------------------------
st.subheader("🏢 Empresa que estou representando")
col1, col2 = st.columns([2, 3])
with col1:
    opcoes = ["➕ Nova empresa"] + [f"{e['nome']} — {e['cnpj']}" for e in st.session_state.empresas]
    escolha = st.selectbox("Empresas salvas", opcoes)

if escolha == "➕ Nova empresa":
    with col2:
        st.write("")
    c1, c2 = st.columns(2)
    empresa_nome = c1.text_input("Nome da empresa representada")
    empresa_cnpj = c2.text_input("CNPJ")
    if st.button("💾 Salvar empresa"):
        if empresa_nome and empresa_cnpj:
            st.session_state.empresas.append({"nome": empresa_nome, "cnpj": empresa_cnpj})
            salvar_empresas(st.session_state.empresas)
            st.success(f"Empresa '{empresa_nome}' salva!")
            st.rerun()
        else:
            st.warning("Preencha nome e CNPJ para salvar.")
else:
    idx = opcoes.index(escolha) - 1
    empresa_nome = st.session_state.empresas[idx]["nome"]
    empresa_cnpj = st.session_state.empresas[idx]["cnpj"]
    st.info(f"**{empresa_nome}**  |  CNPJ: {empresa_cnpj}")

st.divider()

# ---------------- CONTRATANTE --------------------------------------
st.subheader("📇 Empresa contratante")
cliente_nome = st.text_input("Nome da empresa contratante (opcional)")
ce1, ce2 = st.columns(2)
email1 = ce1.text_input("E-mail contratante 1")
email2 = ce2.text_input("E-mail contratante 2")

st.divider()

# ---------------- MODO DE COBRANÇA ---------------------------------
st.subheader("💰 Tipo de cobrança")
modo = st.radio("Como cobrar este orçamento?",
                ["Por hora trabalhada", "Trabalho fechado (valor fixo)"],
                horizontal=True)

dados_pdf = {
    "empresa_nome": empresa_nome or "-",
    "empresa_cnpj": empresa_cnpj or "-",
    "cliente_nome": cliente_nome,
    "email1": email1,
    "email2": email2,
    "numero": datetime.now().strftime("%Y%m%d-%H%M"),
    "data": date.today(),
    "valor_hora": valor_hora,
    "jornada": jornada,
    "pct_extra": pct_extra,
    "pct_dom_fer": pct_dom_fer,
}

if modo == "Trabalho fechado (valor fixo)":
    dados_pdf["modo"] = "fechado"
    valor_fechado = st.number_input("Valor do trabalho fechado (R$)", min_value=0.0, value=0.0, step=50.0)
    descricao_fechado = st.text_area("Descrição do serviço fechado")
    dados_pdf["valor_fechado"] = valor_fechado
    dados_pdf["descricao_fechado"] = descricao_fechado
    dados_pdf["total"] = valor_fechado
    st.metric("Valor total", brl(valor_fechado))

else:
    dados_pdf["modo"] = "horas"
    st.markdown("**Lançamento de horas** — adicione uma linha por dia trabalhado. "
                "Marque *Feriado* quando aplicável (domingo é detectado sozinho).")

    df_inicial = pd.DataFrame([
        {"Data": date.today(), "Descrição": "", "Horas": 8.0, "Feriado": False},
    ])
    edit = st.data_editor(
        df_inicial,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "Descrição": st.column_config.TextColumn("Descrição"),
            "Horas": st.column_config.NumberColumn("Horas", min_value=0.0, step=0.5),
            "Feriado": st.column_config.CheckboxColumn("Feriado"),
        },
        key="tabela_horas",
    )

    linhas = []
    tot_normal = tot_extra = tot_domfer = total = 0.0
    for _, row in edit.iterrows():
        if row["Data"] is None or not row["Horas"]:
            continue
        calc = calcular_linha(row, valor_hora, jornada, pct_extra, pct_dom_fer)
        dt = row["Data"]
        if isinstance(dt, str):
            dt = datetime.strptime(dt, "%Y-%m-%d").date()
        linhas.append({
            "data": dt,
            "descricao": str(row["Descrição"] or ""),
            "dia_semana": calc["dia_semana"],
            "h_normal": calc["h_normal"],
            "h_extra": calc["h_extra"],
            "h_domfer": calc["h_domfer"],
            "valor": calc["valor"],
        })
        tot_normal += calc["h_normal"]
        tot_extra += calc["h_extra"]
        tot_domfer += calc["h_domfer"]
        total += calc["valor"]

    dados_pdf.update({
        "linhas": linhas,
        "tot_normal": tot_normal,
        "tot_extra": tot_extra,
        "tot_domfer": tot_domfer,
        "total": total,
    })

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Horas normais", horas_fmt(tot_normal))
    m2.metric("Horas extras", horas_fmt(tot_extra))
    m3.metric("Dom/Feriado", horas_fmt(tot_domfer))
    m4.metric("VALOR TOTAL", brl(total))

st.divider()

# ---------------- OBSERVAÇÕES + GERAR PDF --------------------------
observacoes = st.text_area("Observações (opcional)")
dados_pdf["observacoes"] = observacoes

if st.button("📥 Gerar orçamento em PDF", type="primary"):
    if not empresa_nome or empresa_nome == "-":
        st.error("Defina a empresa que você está representando.")
    else:
        pdf_bytes = gerar_pdf(dados_pdf)
        nome_arq = f"orcamento_{dados_pdf['numero']}.pdf"
        st.success("Orçamento gerado com sucesso!")
        st.download_button("⬇️ Baixar PDF", data=pdf_bytes, file_name=nome_arq,
                           mime="application/pdf")
