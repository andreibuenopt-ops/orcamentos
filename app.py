import json
import os
from datetime import date, datetime, time

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
# PERSISTÊNCIA DE EMPRESAS
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
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def hhmm(h):
    """Converte 7.55 -> '7h33'."""
    h = float(h or 0)
    total_min = int(round(h * 60))
    return f"{total_min // 60}h{total_min % 60:02d}"


def horas_fmt(h):
    """'7h33 (7,55 h)'"""
    dec = f"{float(h or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{hhmm(h)} ({dec} h)"


def _s(txt):
    if txt is None:
        return ""
    txt = str(txt)
    for k, v in {"—": "-", "–": "-", "…": "...", "’": "'", "‘": "'",
                 "“": '"', "”": '"', "•": "-"}.items():
        txt = txt.replace(k, v)
    return txt.encode("latin-1", "replace").decode("latin-1")


def to_date(dt):
    if isinstance(dt, str):
        return datetime.strptime(dt[:10], "%Y-%m-%d").date()
    if isinstance(dt, datetime):
        return dt.date()
    if hasattr(dt, "to_pydatetime"):
        return dt.to_pydatetime().date()
    return dt


def to_time(v):
    """Normaliza entrada para datetime.time (aceita time, str '07:18', NaT/None)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.time()
    if hasattr(v, "to_pydatetime"):
        try:
            return v.to_pydatetime().time()
        except Exception:
            return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        for fmt in ("%H:%M:%S", "%H:%M", "%H%M"):
            try:
                return datetime.strptime(v, fmt).time()
            except ValueError:
                continue
    return None


def duracao(ini, fim):
    """Horas decimais entre dois horários. Vira a meia-noite se fim < início."""
    ini, fim = to_time(ini), to_time(fim)
    if ini is None or fim is None:
        return 0.0
    base = date(2000, 1, 1)
    d = (datetime.combine(base, fim) - datetime.combine(base, ini)).total_seconds() / 3600
    if d < 0:
        d += 24
    return round(d, 4)


def fmt_periodo(ini, fim):
    ini, fim = to_time(ini), to_time(fim)
    if ini is None or fim is None:
        return ""
    return f"{ini:%H:%M} as {fim:%H:%M}"


# ------------------------------------------------------------------
# MOTOR DE CÁLCULO
# ------------------------------------------------------------------
def calcular_dia(dt, h_total, feriado, valor_hora, jornada, pct_extra, pct_dom_fer):
    dt = to_date(dt)
    h_total = float(h_total or 0)
    especial = (dt.weekday() == 6) or bool(feriado)

    h_normal = h_extra = h_domfer = 0.0
    if especial:
        h_domfer = h_total
        valor = h_total * valor_hora * (1 + pct_dom_fer / 100)
    else:
        h_normal = min(h_total, jornada)
        h_extra = max(0.0, h_total - jornada)
        valor = h_normal * valor_hora + h_extra * valor_hora * (1 + pct_extra / 100)

    return {"dia_semana": DIAS_SEMANA[dt.weekday()], "h_normal": h_normal,
            "h_extra": h_extra, "h_domfer": h_domfer, "valor": valor}


# ------------------------------------------------------------------
# PDF
# ------------------------------------------------------------------
class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, "ORCAMENTO DE SERVICOS", ln=True, align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Gerado em {datetime.now():%d/%m/%Y %H:%M} - Pagina {self.page_no()}",
                  align="C")
        self.set_text_color(0, 0, 0)


LARG = [16, 10, 27, 27, 30, 12, 12, 12, 14, 21]
CAB = ["Data", "Dia", "Periodo 1", "Periodo 2", "Descricao",
       "Norm", "Extra", "D/F", "Total", "Valor"]
ALIGN = ["C", "C", "C", "C", "L", "R", "R", "R", "R", "R"]


def bloco_titulo(pdf, texto):
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, _s(texto), ln=True, fill=True)


def cabecalho_tabela(pdf):
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(225, 225, 225)
    for w, c in zip(LARG, CAB):
        pdf.cell(w, 6, _s(c), border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 7)


def gerar_pdf(d):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    bloco_titulo(pdf, "PRESTADOR / EMPRESA REPRESENTADA")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"Empresa: {d['empresa_nome']}"), ln=True)
    pdf.cell(0, 6, _s(f"CNPJ: {d['empresa_cnpj']}"), ln=True)
    pdf.ln(3)

    bloco_titulo(pdf, "CONTRATANTE")
    pdf.set_font("Helvetica", "", 10)
    if d["cliente_nome"]:
        pdf.cell(0, 6, _s(f"Empresa: {d['cliente_nome']}"), ln=True)
    if d["email1"]:
        pdf.cell(0, 6, _s(f"E-mail 1: {d['email1']}"), ln=True)
    if d["email2"]:
        pdf.cell(0, 6, _s(f"E-mail 2: {d['email2']}"), ln=True)
    pdf.ln(2)
    pdf.cell(0, 6, _s(f"Orcamento no: {d['numero']}    Data: {d['data']:%d/%m/%Y}"), ln=True)
    pdf.ln(2)

    if d["modo"] == "fechado":
        bloco_titulo(pdf, "SERVICO (TRABALHO FECHADO)")
        pdf.set_font("Helvetica", "", 10)
        if d.get("descricao_fechado"):
            pdf.multi_cell(0, 6, _s(f"Descricao: {d['descricao_fechado']}"))
        if d.get("equipe_nomes"):
            pdf.ln(1)
            pdf.multi_cell(0, 6, _s("Equipe alocada: " + ", ".join(d["equipe_nomes"])))
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_fill_color(230, 240, 255)
        pdf.cell(0, 10, _s(f"VALOR TOTAL: {brl(d['valor_fechado'])}"), ln=True,
                 fill=True, align="R")
    else:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _s(f"Jornada normal/dia: {hhmm(d['jornada'])}  |  "
                          f"Hora extra: +{d['pct_extra']:.0f}%  |  "
                          f"Domingo/Feriado: +{d['pct_dom_fer']:.0f}%"), ln=True)
        pdf.ln(2)

        for p in d["pessoas"]:
            if pdf.get_y() > 230:
                pdf.add_page()

            titulo = p["nome"] + (f" - {p['funcao']}" if p.get("funcao") else "")
            bloco_titulo(pdf, titulo)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 5, _s(f"Valor da hora: {brl(p['valor_hora'])}"), ln=True)
            cabecalho_tabela(pdf)

            for l in p["linhas"]:
                if pdf.get_y() > 262:
                    pdf.add_page()
                    cabecalho_tabela(pdf)
                desc = l["descricao"]
                if len(desc) > 20:
                    desc = desc[:19] + "."
                vals = [l["data"].strftime("%d/%m/%y"), l["dia_semana"][:3],
                        l["periodo1"], l["periodo2"], desc,
                        hhmm(l["h_normal"]), hhmm(l["h_extra"]), hhmm(l["h_domfer"]),
                        hhmm(l["h_total"]), brl(l["valor"]).replace("R$ ", "")]
                for w, v, a in zip(LARG, vals, ALIGN):
                    pdf.cell(w, 6, _s(v), border=1, align=a)
                pdf.ln()

            pdf.set_font("Helvetica", "B", 7)
            pdf.set_fill_color(245, 245, 245)
            pdf.cell(sum(LARG[:5]), 6, _s("SUBTOTAL"), border=1, align="R", fill=True)
            for w, v in zip(LARG[5:], [hhmm(p["tot_normal"]), hhmm(p["tot_extra"]),
                                       hhmm(p["tot_domfer"]), hhmm(p["tot_horas"]),
                                       brl(p["total"]).replace("R$ ", "")]):
                pdf.cell(w, 6, _s(v), border=1, align="R", fill=True)
            pdf.ln(10)

        if pdf.get_y() > 225:
            pdf.add_page()
        bloco_titulo(pdf, "RESUMO GERAL")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _s(f"Pessoas na prestacao: {len(d['pessoas'])}"), ln=True)
        pdf.cell(0, 6, _s(f"Total horas normais: {horas_fmt(d['tot_normal'])}"), ln=True)
        pdf.cell(0, 6, _s(f"Total horas extras: {horas_fmt(d['tot_extra'])}"), ln=True)
        pdf.cell(0, 6, _s(f"Total domingo/feriado: {horas_fmt(d['tot_domfer'])}"), ln=True)
        pdf.cell(0, 6, _s(f"Total geral de horas: {horas_fmt(d['tot_horas'])}"), ln=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_fill_color(230, 240, 255)
        pdf.cell(0, 10, _s(f"VALOR TOTAL: {brl(d['total'])}"), ln=True, fill=True, align="R")

    if d.get("observacoes"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, _s("Observacoes:"), ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _s(d["observacoes"]))

    return bytes(pdf.output())


# ==================================================================
# INTERFACE
# ==================================================================
st.title("📄 Gerador de Orçamentos e Horas Trabalhadas")

if "empresas" not in st.session_state:
    st.session_state.empresas = carregar_empresas()

with st.sidebar:
    st.header("⚙️ Parâmetros de cálculo")
    jornada = st.number_input("Jornada normal por dia (h)", min_value=1.0, value=8.0, step=0.5,
                              help="Horas acima disso, em dia útil, viram hora extra.")
    pct_extra = st.number_input("Acréscimo hora extra (%)", min_value=0.0, value=50.0, step=5.0)
    pct_dom_fer = st.number_input("Acréscimo domingo/feriado (%)", min_value=0.0,
                                  value=100.0, step=5.0)
    st.caption("Domingo é detectado automaticamente pela data. "
               "Sábado conta como dia útil (extra acima da jornada).")

# ---------------- EMPRESA REPRESENTADA ----------------
st.subheader("🏢 Empresa que estou representando")
opcoes = ["➕ Nova empresa"] + [f"{e['nome']} — {e['cnpj']}" for e in st.session_state.empresas]
escolha = st.selectbox("Empresas salvas", opcoes)

if escolha == "➕ Nova empresa":
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

# ---------------- CONTRATANTE ----------------
st.subheader("📇 Empresa contratante")
cliente_nome = st.text_input("Nome da empresa contratante (opcional)")
ce1, ce2 = st.columns(2)
email1 = ce1.text_input("E-mail contratante 1")
email2 = ce2.text_input("E-mail contratante 2")

st.divider()

# ---------------- EQUIPE ----------------
st.subheader("👥 Equipe da prestação de serviço")
st.caption("Adicione quantas pessoas quiser. Cada uma tem valor/hora e função próprios.")

if "equipe_base" not in st.session_state:
    st.session_state.equipe_base = pd.DataFrame(
        [{"Nome": "", "Função": "", "Valor hora (R$)": 50.0}])

equipe_df = st.data_editor(
    st.session_state.equipe_base,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Nome": st.column_config.TextColumn("Nome"),
        "Função": st.column_config.TextColumn("Função / Cargo"),
        "Valor hora (R$)": st.column_config.NumberColumn(
            "Valor hora (R$)", min_value=0.0, step=5.0, format="%.2f"),
    },
    key="editor_equipe",
)

equipe = [
    {"nome": str(r["Nome"]).strip(),
     "funcao": str(r["Função"] or "").strip(),
     "valor_hora": float(r["Valor hora (R$)"] or 0)}
    for _, r in equipe_df.iterrows() if str(r["Nome"]).strip()
]

if not equipe:
    st.warning("Cadastre ao menos uma pessoa na equipe acima para lançar horas.")

st.divider()

# ---------------- MODO ----------------
st.subheader("💰 Tipo de cobrança")
modo = st.radio("Como cobrar este orçamento?",
                ["Por hora trabalhada", "Trabalho fechado (valor fixo)"], horizontal=True)

dados = {
    "empresa_nome": empresa_nome or "-", "empresa_cnpj": empresa_cnpj or "-",
    "cliente_nome": cliente_nome, "email1": email1, "email2": email2,
    "numero": datetime.now().strftime("%Y%m%d-%H%M"), "data": date.today(),
    "jornada": jornada, "pct_extra": pct_extra, "pct_dom_fer": pct_dom_fer,
}

if modo == "Trabalho fechado (valor fixo)":
    dados["modo"] = "fechado"
    valor_fechado = st.number_input("Valor do trabalho fechado (R$)", min_value=0.0,
                                    value=0.0, step=50.0)
    dados["descricao_fechado"] = st.text_area("Descrição do serviço fechado")
    dados["valor_fechado"] = valor_fechado
    dados["equipe_nomes"] = [p["nome"] for p in equipe]
    dados["total"] = valor_fechado
    st.metric("Valor total", brl(valor_fechado))
    st.caption("No modo fechado as horas são ignoradas — a equipe aparece apenas "
               "como relação de pessoas alocadas.")

else:
    dados["modo"] = "horas"

    if equipe:
        st.markdown("**Lançamento de horários por pessoa** — informe entrada e saída de cada "
                    "período. O app calcula a duração automaticamente.")
        st.caption("Ex.: 07:18 às 11:42 + 12:45 às 15:54 = 7h33. "
                   "Se só houver um período, deixe o Período 2 em branco. "
                   "Saída menor que entrada é interpretada como virada de meia-noite.")

        abas = st.tabs([p["nome"] for p in equipe])
        pessoas = []
        g_normal = g_extra = g_domfer = g_horas = g_total = 0.0

        for aba, p in zip(abas, equipe):
            with aba:
                st.caption(f"{p['funcao'] or 'Sem função definida'}  |  "
                           f"Valor hora: {brl(p['valor_hora'])}")

                base = pd.DataFrame([{
                    "Data": date.today(), "Entrada 1": time(7, 18), "Saída 1": time(11, 42),
                    "Entrada 2": time(12, 45), "Saída 2": time(15, 54),
                    "Descrição": "", "Feriado": False,
                }])

                tabela = st.data_editor(
                    base, num_rows="dynamic", use_container_width=True,
                    column_config={
                        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                        "Entrada 1": st.column_config.TimeColumn("Entrada 1", format="HH:mm",
                                                                 step=60),
                        "Saída 1": st.column_config.TimeColumn("Saída 1", format="HH:mm", step=60),
                        "Entrada 2": st.column_config.TimeColumn("Entrada 2", format="HH:mm",
                                                                 step=60),
                        "Saída 2": st.column_config.TimeColumn("Saída 2", format="HH:mm", step=60),
                        "Descrição": st.column_config.TextColumn("Descrição do serviço"),
                        "Feriado": st.column_config.CheckboxColumn("Feriado"),
                    },
                    key=f"horas_{p['nome']}",
                )

                linhas = []
                t_normal = t_extra = t_domfer = t_valor = 0.0
                for _, row in tabela.iterrows():
                    if row["Data"] is None:
                        continue
                    h1 = duracao(row["Entrada 1"], row["Saída 1"])
                    h2 = duracao(row["Entrada 2"], row["Saída 2"])
                    h_total = h1 + h2
                    if h_total <= 0:
                        continue

                    c = calcular_dia(row["Data"], h_total, row["Feriado"], p["valor_hora"],
                                     jornada, pct_extra, pct_dom_fer)
                    linhas.append({
                        "data": to_date(row["Data"]),
                        "descricao": str(row["Descrição"] or ""),
                        "dia_semana": c["dia_semana"],
                        "periodo1": fmt_periodo(row["Entrada 1"], row["Saída 1"]),
                        "periodo2": fmt_periodo(row["Entrada 2"], row["Saída 2"]),
                        "h_total": h_total, "h_normal": c["h_normal"], "h_extra": c["h_extra"],
                        "h_domfer": c["h_domfer"], "valor": c["valor"],
                    })
                    t_normal += c["h_normal"]
                    t_extra += c["h_extra"]
                    t_domfer += c["h_domfer"]
                    t_valor += c["valor"]

                if linhas:
                    st.markdown("**Horas calculadas**")
                    st.dataframe(pd.DataFrame([{
                        "Data": l["data"].strftime("%d/%m/%Y"),
                        "Dia": l["dia_semana"],
                        "Período 1": l["periodo1"] or "-",
                        "Período 2": l["periodo2"] or "-",
                        "Total do dia": hhmm(l["h_total"]),
                        "Normais": hhmm(l["h_normal"]),
                        "Extras": hhmm(l["h_extra"]),
                        "Dom/Fer": hhmm(l["h_domfer"]),
                        "Valor": brl(l["valor"]),
                    } for l in linhas]), use_container_width=True, hide_index=True)

                t_horas = t_normal + t_extra + t_domfer
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Normais", hhmm(t_normal))
                m2.metric("Extras", hhmm(t_extra))
                m3.metric("Dom/Feriado", hhmm(t_domfer))
                m4.metric("Subtotal", brl(t_valor))

                pessoas.append({**p, "linhas": linhas, "tot_normal": t_normal,
                                "tot_extra": t_extra, "tot_domfer": t_domfer,
                                "tot_horas": t_horas, "total": t_valor})
                g_normal += t_normal
                g_extra += t_extra
                g_domfer += t_domfer
                g_horas += t_horas
                g_total += t_valor

        dados.update({"pessoas": pessoas, "tot_normal": g_normal, "tot_extra": g_extra,
                      "tot_domfer": g_domfer, "tot_horas": g_horas, "total": g_total})

        st.divider()
        st.markdown("### 📊 Resumo geral")
        if pessoas:
            st.dataframe(pd.DataFrame([{
                "Pessoa": p["nome"], "Função": p["funcao"],
                "Valor hora": brl(p["valor_hora"]),
                "Normais": hhmm(p["tot_normal"]), "Extras": hhmm(p["tot_extra"]),
                "Dom/Fer": hhmm(p["tot_domfer"]), "Total": hhmm(p["tot_horas"]),
                "Subtotal": brl(p["total"]),
            } for p in pessoas]), use_container_width=True, hide_index=True)

        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Pessoas", len(pessoas))
        r2.metric("H. normais", hhmm(g_normal))
        r3.metric("H. extras", hhmm(g_extra))
        r4.metric("Dom/Feriado", hhmm(g_domfer))
        r5.metric("VALOR TOTAL", brl(g_total))
    else:
        dados.update({"pessoas": [], "tot_normal": 0, "tot_extra": 0,
                      "tot_domfer": 0, "tot_horas": 0, "total": 0})

st.divider()

dados["observacoes"] = st.text_area("Observações (opcional)")

if st.button("📥 Gerar orçamento em PDF", type="primary"):
    if not empresa_nome or empresa_nome == "-":
        st.error("Defina a empresa que você está representando.")
    elif dados["modo"] == "horas" and not dados.get("pessoas"):
        st.error("Cadastre ao menos uma pessoa e lance os horários.")
    else:
        st.success("Orçamento gerado com sucesso!")
        st.download_button("⬇️ Baixar PDF", data=gerar_pdf(dados),
                           file_name=f"orcamento_{dados['numero']}.pdf",
                           mime="application/pdf")
