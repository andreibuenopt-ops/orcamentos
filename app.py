import json
import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
from fpdf import FPDF

st.set_page_config(page_title="Gerador de Orçamentos", page_icon="📄", layout="wide")

EMPRESAS_FILE = "empresas.json"
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
TIPOS = ["comercial", "extra_util", "sabado", "domfer"]
ROTULOS = {"comercial": "Hora Comercial", "extra_util": "Hora Extra - Dia Útil",
           "sabado": "Sábado", "domfer": "Domingo / Feriado"}


# ---------------- PERSISTÊNCIA ----------------
def carregar_empresas():
    if os.path.exists(EMPRESAS_FILE):
        try:
            with open(EMPRESAS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def salvar_empresas(e):
    with open(EMPRESAS_FILE, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=2)


# ---------------- HELPERS ----------------
def brl(v):
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def hhmm(h):
    m = int(round(float(h or 0) * 60))
    return f"{m // 60}h{m % 60:02d}"


def num(v, casas=2):
    return f"{float(v or 0):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _s(txt):
    if txt is None:
        return ""
    txt = str(txt)
    for k, v in {"—": "-", "–": "-", "…": "...", "’": "'", "‘": "'",
                 "“": '"', "”": '"', "•": "-", "º": "o", "ª": "a"}.items():
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
        for fmt in ("%H:%M:%S", "%H:%M", "%H%M"):
            try:
                return datetime.strptime(v, fmt).time()
            except ValueError:
                continue
    return None


def _m(t):
    return t.hour * 60 + t.minute


def fmt_periodo(i, f):
    i, f = to_time(i), to_time(f)
    return "" if (i is None or f is None) else f"{i:%H:%M} as {f:%H:%M}"


# ---------------- MOTOR: CLASSIFICAÇÃO POR JANELA ----------------
def classificar(dt, ini, fim, janelas, feriado=False):
    """Divide o intervalo nos 4 tipos de hora conforme a janela comercial.
    Trata virada de meia-noite reclassificando o dia seguinte."""
    ini, fim = to_time(ini), to_time(fim)
    r = {t: 0.0 for t in TIPOS}
    if ini is None or fim is None:
        return r
    a, b = _m(ini), _m(fim)
    if b <= a:
        b += 1440
    for k in (0, 1):
        s, e = max(a, k * 1440), min(b, (k + 1) * 1440)
        if e <= s:
            continue
        d = to_date(dt) + timedelta(days=k)
        h = (e - s) / 60
        if d.weekday() == 6 or (feriado and k == 0):
            r["domfer"] += h
        elif d.weekday() == 5:
            r["sabado"] += h
        else:
            ls, le = s - k * 1440, e - k * 1440
            com = sum(max(0, min(le, w2) - max(ls, w1)) for w1, w2 in janelas)
            r["comercial"] += com / 60
            r["extra_util"] += ((le - ls) - com) / 60
    return r


def tarifas(base, cfg):
    return {"comercial": base,
            "extra_util": base * (1 + cfg["pct_extra"] / 100),
            "sabado": base * (1 + cfg["pct_sabado"] / 100),
            "domfer": base * (1 + cfg["pct_domfer"] / 100)}


def multiplicadores(cfg):
    return {"comercial": 1.0,
            "extra_util": 1 + cfg["pct_extra"] / 100,
            "sabado": 1 + cfg["pct_sabado"] / 100,
            "domfer": 1 + cfg["pct_domfer"] / 100}


def texto_horarios(cfg):
    j = cfg["janelas_txt"]
    return {"comercial": f"{j} - seg a sex",
            "extra_util": f"Antes das {cfg['m1']:%H:%M}, entre {cfg['m2']:%H:%M}-{cfg['t1']:%H:%M} "
                          f"ou apos {cfg['t2']:%H:%M}",
            "sabado": "Qualquer horario",
            "domfer": "Qualquer horario"}


# ---------------- PDF ----------------
class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 9, "ORCAMENTO DE SERVICOS", ln=True, align="C")
        self.ln(1)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Gerado em {datetime.now():%d/%m/%Y %H:%M} - Pagina {self.page_no()}",
                  align="C")
        self.set_text_color(0, 0, 0)


def titulo(pdf, txt, tam=11):
    pdf.set_font("Helvetica", "B", tam)
    pdf.set_fill_color(238, 238, 238)
    pdf.cell(0, 7.5, _s(txt), ln=True, fill=True)


LARG = [15, 9, 24, 24, 26, 12, 12, 12, 12, 13, 19]
CAB = ["Data", "Dia", "Periodo 1", "Periodo 2", "Descricao",
       "Comerc", "Extra", "Sabado", "Dom/Fer", "Total", "Valor"]
ALIGN = ["C", "C", "C", "C", "L", "R", "R", "R", "R", "R", "R"]


def cab_tabela(pdf):
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_fill_color(222, 222, 222)
    for w, c in zip(LARG, CAB):
        pdf.cell(w, 5.5, _s(c), border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 6.5)


def tabela_composicao(pdf, d):
    """Tabela COMPOSIÇÃO E CRITÉRIOS - gerada a partir dos parâmetros."""
    cfg, base = d["cfg"], d["base"]
    tf, mult, hor = tarifas(base, cfg), multiplicadores(cfg), texto_horarios(cfg)
    pct = {"comercial": 0, "extra_util": cfg["pct_extra"],
           "sabado": cfg["pct_sabado"], "domfer": cfg["pct_domfer"]}

    titulo(pdf, "COMPOSICAO E CRITERIOS DE COBRANCA DE HORA HOMEM")
    pdf.set_font("Helvetica", "", 9)
    pdf.ln(1)
    pdf.multi_cell(0, 4.6, _s(
        f"Valor base da hora comercial: {brl(base)} por hora homem (HH).\n"
        f"Horario comercial: {cfg['janelas_txt']}, de segunda a sexta-feira.\n"
        f"Horas fora do horario comercial (dias uteis): servicos antes das {cfg['m1']:%H:%M}, "
        f"entre {cfg['m2']:%H:%M} e {cfg['t1']:%H:%M} (almoco) ou apos {cfg['t2']:%H:%M} tem "
        f"acrescimo de {num(cfg['pct_extra'],0)}% sobre o valor base, totalizando "
        f"{brl(tf['extra_util'])}/h.\n"
        f"Sabados: independentemente do horario, acrescimo de {num(cfg['pct_sabado'],0)}% sobre o "
        f"valor base, totalizando {brl(tf['sabado'])}/h.\n"
        f"Domingos e feriados: nacionais ou estaduais, acrescimo de {num(cfg['pct_domfer'],0)}% "
        f"sobre o valor base, totalizando {brl(tf['domfer'])}/h.\n"
        f"Fracionamento de horas: as horas sao cobradas de forma proporcional. Periodos dentro e "
        f"fora do horario comercial no mesmo dia sao calculados separadamente, cada qual com seu "
        f"respectivo valor."))
    pdf.ln(2)

    w = [46, 74, 30, 32]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(222, 222, 222)
    for wi, c in zip(w, ["TIPO DE HORA", "HORARIO", "ADICIONAL", "VALOR (R$/h)"]):
        pdf.cell(wi, 6, _s(c), border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for t in TIPOS:
        ad = "1,00x" if t == "comercial" else f"{num(mult[t])}x (+{num(pct[t],0)}%)"
        for wi, v, al in zip(w, [ROTULOS[t], hor[t], ad, f"{brl(tf[t])} / h"],
                             ["L", "L", "C", "R"]):
            pdf.cell(wi, 5.5, _s(v), border=1, align=al)
        pdf.ln()
    pdf.ln(3)


def gerar_pdf(d):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)

    titulo(pdf, "PRESTADOR / EMPRESA REPRESENTADA")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5.5, _s(f"Empresa: {d['empresa_nome']}"), ln=True)
    pdf.cell(0, 5.5, _s(f"CNPJ: {d['empresa_cnpj']}"), ln=True)
    pdf.ln(2)

    titulo(pdf, "CONTRATANTE")
    pdf.set_font("Helvetica", "", 10)
    if d["cliente_nome"]:
        pdf.cell(0, 5.5, _s(f"Empresa: {d['cliente_nome']}"), ln=True)
    if d["email1"]:
        pdf.cell(0, 5.5, _s(f"E-mail 1: {d['email1']}"), ln=True)
    if d["email2"]:
        pdf.cell(0, 5.5, _s(f"E-mail 2: {d['email2']}"), ln=True)
    pdf.cell(0, 5.5, _s(f"Orcamento no: {d['numero']}    Data: {d['data']:%d/%m/%Y}"), ln=True)
    pdf.ln(2)

    # ESCOPO
    titulo(pdf, "ESCOPO DO SERVICO")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5.5, _s(d["escopo"]), ln=True)
    pdf.set_font("Helvetica", "", 9)
    if d.get("escopo_desc"):
        pdf.multi_cell(0, 4.6, _s(d["escopo_desc"]))
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5.5, _s(f"Material solicitado pela empresa contratante: {d['material_flag']}"),
             ln=True)
    if d.get("material_desc"):
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4.6, _s(d["material_desc"]))
    pdf.ln(3)

    if d["modo"] == "fechado":
        titulo(pdf, "SERVICO (TRABALHO FECHADO)")
        pdf.set_font("Helvetica", "", 10)
        if d.get("descricao_fechado"):
            pdf.multi_cell(0, 5, _s(d["descricao_fechado"]))
        if d.get("equipe_nomes"):
            pdf.ln(1)
            pdf.multi_cell(0, 5, _s("Equipe alocada: " + ", ".join(d["equipe_nomes"])))
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_fill_color(228, 238, 252)
        pdf.cell(0, 9, _s(f"VALOR TOTAL: {brl(d['valor_fechado'])}"), ln=True, fill=True,
                 align="R")
    else:
        tabela_composicao(pdf, d)

        for p in d["pessoas"]:
            if pdf.get_y() > 225:
                pdf.add_page()
            titulo(pdf, p["nome"] + (f" - {p['funcao']}" if p.get("funcao") else ""), 10)
            pdf.set_font("Helvetica", "", 8.5)
            tf = tarifas(p["valor_hora"], d["cfg"])
            pdf.cell(0, 4.6, _s(f"Base: {brl(p['valor_hora'])}/h  |  Extra: {brl(tf['extra_util'])}/h"
                                f"  |  Sabado: {brl(tf['sabado'])}/h  |  "
                                f"Dom/Fer: {brl(tf['domfer'])}/h"), ln=True)
            cab_tabela(pdf)
            for l in p["linhas"]:
                if pdf.get_y() > 258:
                    pdf.add_page()
                    cab_tabela(pdf)
                desc = l["descricao"][:17] + "." if len(l["descricao"]) > 18 else l["descricao"]
                vals = [l["data"].strftime("%d/%m/%y"), l["dia_semana"][:3],
                        l["periodo1"], l["periodo2"], desc,
                        hhmm(l["comercial"]), hhmm(l["extra_util"]), hhmm(l["sabado"]),
                        hhmm(l["domfer"]), hhmm(l["h_total"]),
                        brl(l["valor"]).replace("R$ ", "")]
                for w, v, a in zip(LARG, vals, ALIGN):
                    pdf.cell(w, 5.5, _s(v), border=1, align=a)
                pdf.ln()
            pdf.set_font("Helvetica", "B", 6.5)
            pdf.set_fill_color(243, 243, 243)
            pdf.cell(sum(LARG[:5]), 5.5, _s("SUBTOTAL"), border=1, align="R", fill=True)
            for w, v in zip(LARG[5:], [hhmm(p["comercial"]), hhmm(p["extra_util"]),
                                       hhmm(p["sabado"]), hhmm(p["domfer"]),
                                       hhmm(p["tot_horas"]),
                                       brl(p["total"]).replace("R$ ", "")]):
                pdf.cell(w, 5.5, _s(v), border=1, align="R", fill=True)
            pdf.ln(9)

        if pdf.get_y() > 215:
            pdf.add_page()
        titulo(pdf, "RESUMO GERAL")
        w = [64, 40, 40, 38]
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(222, 222, 222)
        for wi, c in zip(w, ["TIPO DE HORA", "TOTAL DE HORAS", "VALOR (R$/h)", "SUBTOTAL"]):
            pdf.cell(wi, 6, _s(c), border=1, align="C", fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        tf = tarifas(d["base"], d["cfg"])
        for t in TIPOS:
            if d["tot"][t] <= 0:
                continue
            vh = "variavel" if d["multi_base"] else f"{brl(tf[t])} / h"
            for wi, v, al in zip(w, [ROTULOS[t], hhmm(d["tot"][t]), vh,
                                     brl(d["subtotais"][t])], ["L", "R", "R", "R"]):
                pdf.cell(wi, 5.5, _s(v), border=1, align=al)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(243, 243, 243)
        pdf.cell(w[0], 6, _s("TOTAL"), border=1, align="R", fill=True)
        pdf.cell(w[1], 6, _s(hhmm(d["tot_horas"])), border=1, align="R", fill=True)
        pdf.cell(w[2], 6, "", border=1, fill=True)
        pdf.cell(w[3], 6, _s(brl(d["total"])), border=1, align="R", fill=True)
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _s(f"Pessoas na prestacao: {len(d['pessoas'])}"), ln=True)
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_fill_color(228, 238, 252)
        pdf.cell(0, 9, _s(f"VALOR TOTAL: {brl(d['total'])}"), ln=True, fill=True, align="R")

    if d.get("observacoes"):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5.5, _s("Observacoes:"), ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4.6, _s(d["observacoes"]))

    return bytes(pdf.output())


# ==================================================================
# INTERFACE
# ==================================================================
st.title("📄 Gerador de Orçamentos e Horas Trabalhadas")

if "empresas" not in st.session_state:
    st.session_state.empresas = carregar_empresas()

with st.sidebar:
    st.header("⚙️ Composição de valores")
    base = st.number_input("Valor base da hora comercial (R$)", min_value=0.0, value=50.0, step=5.0)
    st.markdown("**Horário comercial (seg a sex)**")
    c1, c2 = st.columns(2)
    m1 = c1.time_input("Manhã início", value=time(7, 0), step=300)
    m2 = c2.time_input("Manhã fim", value=time(12, 0), step=300)
    c3, c4 = st.columns(2)
    t1 = c3.time_input("Tarde início", value=time(13, 0), step=300)
    t2 = c4.time_input("Tarde fim", value=time(17, 0), step=300)
    st.markdown("**Acréscimos**")
    pct_extra = st.number_input("Extra dia útil (%)", min_value=0.0, value=60.0, step=5.0)
    pct_sabado = st.number_input("Sábado (%)", min_value=0.0, value=60.0, step=5.0)
    pct_domfer = st.number_input("Domingo / Feriado (%)", min_value=0.0, value=100.0, step=5.0)

cfg = {"m1": m1, "m2": m2, "t1": t1, "t2": t2, "pct_extra": pct_extra,
       "pct_sabado": pct_sabado, "pct_domfer": pct_domfer,
       "janelas_txt": f"Das {m1:%H:%M} as {m2:%H:%M} e das {t1:%H:%M} as {t2:%H:%M}"}
JANELAS = [(_m(m1), _m(m2)), (_m(t1), _m(t2))]

# Prévia da composição
tf0, mu0 = tarifas(base, cfg), multiplicadores(cfg)
st.markdown("#### Composição e critérios de cobrança de hora homem")
st.dataframe(pd.DataFrame([
    {"TIPO DE HORA": ROTULOS["comercial"], "HORÁRIO": cfg["janelas_txt"] + " (seg a sex)",
     "ADICIONAL": "1,00x", "VALOR (R$/h)": brl(tf0["comercial"])},
    {"TIPO DE HORA": ROTULOS["extra_util"],
     "HORÁRIO": f"Antes das {m1:%H:%M}, entre {m2:%H:%M}-{t1:%H:%M} ou após {t2:%H:%M}",
     "ADICIONAL": f"{num(mu0['extra_util'])}x (+{num(pct_extra,0)}%)",
     "VALOR (R$/h)": brl(tf0["extra_util"])},
    {"TIPO DE HORA": ROTULOS["sabado"], "HORÁRIO": "Qualquer horário",
     "ADICIONAL": f"{num(mu0['sabado'])}x (+{num(pct_sabado,0)}%)",
     "VALOR (R$/h)": brl(tf0["sabado"])},
    {"TIPO DE HORA": ROTULOS["domfer"], "HORÁRIO": "Qualquer horário",
     "ADICIONAL": f"{num(mu0['domfer'])}x (+{num(pct_domfer,0)}%)",
     "VALOR (R$/h)": brl(tf0["domfer"])},
]), use_container_width=True, hide_index=True)
st.caption("Esta tabela vai para o PDF exatamente com estes valores, calculados a partir dos "
           "parâmetros da barra lateral.")

st.divider()

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
    i = opcoes.index(escolha) - 1
    empresa_nome = st.session_state.empresas[i]["nome"]
    empresa_cnpj = st.session_state.empresas[i]["cnpj"]
    st.info(f"**{empresa_nome}**  |  CNPJ: {empresa_cnpj}")

st.divider()

st.subheader("📇 Empresa contratante")
cliente_nome = st.text_input("Nome da empresa contratante (opcional)")
ce1, ce2 = st.columns(2)
email1 = ce1.text_input("E-mail contratante 1")
email2 = ce2.text_input("E-mail contratante 2")

st.divider()

# ---------------- ESCOPO ----------------
st.subheader("🧰 Escopo do serviço")
esc1, esc2 = st.columns(2)
escopo = esc1.radio("O orçamento contempla:",
                    ["Somente mão de obra", "Mão de obra e material"])
material_flag = esc2.radio("Material solicitado pela empresa contratante:", ["Não", "Sim"])

TXT_MO = ("O presente orcamento contempla exclusivamente o fornecimento de mao de obra "
          "especializada (hora homem). Materiais, pecas, insumos, ferramentas especiais e "
          "equipamentos nao estao inclusos, sendo de responsabilidade da empresa contratante.")
TXT_MOM = ("O presente orcamento contempla o fornecimento de mao de obra especializada "
           "(hora homem) e os materiais relacionados neste documento.")

escopo_desc = st.text_area("Descrição do escopo",
                           value=TXT_MO if escopo == "Somente mão de obra" else TXT_MOM,
                           height=90)
material_desc = ""
if material_flag == "Sim":
    material_desc = st.text_area("Descrição do material solicitado pela contratante", height=70)

st.divider()

# ---------------- EQUIPE ----------------
st.subheader("👥 Equipe da prestação de serviço")
st.caption("Adicione quantas pessoas quiser. O valor base de cada uma pode ser diferente; "
           "os acréscimos (%) são os mesmos para todos.")

if "equipe_base" not in st.session_state:
    st.session_state.equipe_base = pd.DataFrame(
        [{"Nome": "", "Função": "", "Valor base hora (R$)": base}])

equipe_df = st.data_editor(
    st.session_state.equipe_base, num_rows="dynamic", use_container_width=True,
    column_config={
        "Nome": st.column_config.TextColumn("Nome"),
        "Função": st.column_config.TextColumn("Função / Cargo"),
        "Valor base hora (R$)": st.column_config.NumberColumn(
            "Valor base hora (R$)", min_value=0.0, step=5.0, format="%.2f"),
    }, key="editor_equipe")

equipe = [{"nome": str(r["Nome"]).strip(), "funcao": str(r["Função"] or "").strip(),
           "valor_hora": float(r["Valor base hora (R$)"] or 0)}
          for _, r in equipe_df.iterrows() if str(r["Nome"]).strip()]

if not equipe:
    st.warning("Cadastre ao menos uma pessoa na equipe acima para lançar horários.")

st.divider()

st.subheader("💰 Tipo de cobrança")
modo = st.radio("Como cobrar este orçamento?",
                ["Por hora trabalhada", "Trabalho fechado (valor fixo)"], horizontal=True)

d = {"empresa_nome": empresa_nome or "-", "empresa_cnpj": empresa_cnpj or "-",
     "cliente_nome": cliente_nome, "email1": email1, "email2": email2,
     "numero": datetime.now().strftime("%Y%m%d-%H%M"), "data": date.today(),
     "cfg": cfg, "base": base, "escopo": escopo, "escopo_desc": escopo_desc,
     "material_flag": material_flag.upper(), "material_desc": material_desc,
     "multi_base": len({p["valor_hora"] for p in equipe}) > 1}

if modo == "Trabalho fechado (valor fixo)":
    d["modo"] = "fechado"
    d["valor_fechado"] = st.number_input("Valor do trabalho fechado (R$)", min_value=0.0,
                                         value=0.0, step=50.0)
    d["descricao_fechado"] = st.text_area("Descrição do serviço fechado")
    d["equipe_nomes"] = [p["nome"] for p in equipe]
    d["total"] = d["valor_fechado"]
    st.metric("Valor total", brl(d["valor_fechado"]))
    st.caption("No modo fechado as horas são ignoradas.")
else:
    d["modo"] = "horas"
    if equipe:
        st.markdown("**Lançamento de horários por pessoa** — a classificação das horas é "
                    "automática pela janela de horário e pelo dia da semana.")
        st.caption("Ex.: 12:45 às 15:54 numa terça = 0h15 extra (almoço) + 2h54 comercial. "
                   "Saída menor que entrada é interpretada como virada de meia-noite.")

        abas = st.tabs([p["nome"] for p in equipe])
        pessoas = []
        tot = {t: 0.0 for t in TIPOS}
        subtotais = {t: 0.0 for t in TIPOS}
        g_total = 0.0

        for aba, p in zip(abas, equipe):
            with aba:
                tfp = tarifas(p["valor_hora"], cfg)
                st.caption(f"{p['funcao'] or 'Sem função definida'}  |  "
                           f"Comercial {brl(tfp['comercial'])}/h  ·  "
                           f"Extra {brl(tfp['extra_util'])}/h  ·  "
                           f"Sábado {brl(tfp['sabado'])}/h  ·  "
                           f"Dom/Fer {brl(tfp['domfer'])}/h")

                base_df = pd.DataFrame([{
                    "Data": date.today(), "Entrada 1": time(7, 0), "Saída 1": time(12, 0),
                    "Entrada 2": time(13, 0), "Saída 2": time(17, 0),
                    "Descrição": "", "Feriado": False}])
                tabela = st.data_editor(
                    base_df, num_rows="dynamic", use_container_width=True,
                    column_config={
                        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                        "Entrada 1": st.column_config.TimeColumn("Entrada 1", format="HH:mm", step=60),
                        "Saída 1": st.column_config.TimeColumn("Saída 1", format="HH:mm", step=60),
                        "Entrada 2": st.column_config.TimeColumn("Entrada 2", format="HH:mm", step=60),
                        "Saída 2": st.column_config.TimeColumn("Saída 2", format="HH:mm", step=60),
                        "Descrição": st.column_config.TextColumn("Descrição do serviço"),
                        "Feriado": st.column_config.CheckboxColumn("Feriado"),
                    }, key=f"horas_{p['nome']}")

                linhas = []
                pt = {t: 0.0 for t in TIPOS}
                p_valor = 0.0
                for _, row in tabela.iterrows():
                    if row["Data"] is None:
                        continue
                    dt = to_date(row["Data"])
                    r1 = classificar(dt, row["Entrada 1"], row["Saída 1"], JANELAS, row["Feriado"])
                    r2 = classificar(dt, row["Entrada 2"], row["Saída 2"], JANELAS, row["Feriado"])
                    r = {t: r1[t] + r2[t] for t in TIPOS}
                    h_total = sum(r.values())
                    if h_total <= 0:
                        continue
                    valor = sum(r[t] * tfp[t] for t in TIPOS)
                    linhas.append({**r, "data": dt, "descricao": str(row["Descrição"] or ""),
                                   "dia_semana": DIAS_SEMANA[dt.weekday()],
                                   "periodo1": fmt_periodo(row["Entrada 1"], row["Saída 1"]),
                                   "periodo2": fmt_periodo(row["Entrada 2"], row["Saída 2"]),
                                   "h_total": h_total, "valor": valor})
                    for t in TIPOS:
                        pt[t] += r[t]
                        subtotais[t] += r[t] * tfp[t]
                    p_valor += valor

                if linhas:
                    st.markdown("**Horas calculadas**")
                    st.dataframe(pd.DataFrame([{
                        "Data": l["data"].strftime("%d/%m/%Y"), "Dia": l["dia_semana"],
                        "Período 1": l["periodo1"] or "-", "Período 2": l["periodo2"] or "-",
                        "Comercial": hhmm(l["comercial"]), "Extra útil": hhmm(l["extra_util"]),
                        "Sábado": hhmm(l["sabado"]), "Dom/Fer": hhmm(l["domfer"]),
                        "Total": hhmm(l["h_total"]), "Valor": brl(l["valor"]),
                    } for l in linhas]), use_container_width=True, hide_index=True)

                ph = sum(pt.values())
                k = st.columns(5)
                k[0].metric("Comercial", hhmm(pt["comercial"]))
                k[1].metric("Extra útil", hhmm(pt["extra_util"]))
                k[2].metric("Sábado", hhmm(pt["sabado"]))
                k[3].metric("Dom/Feriado", hhmm(pt["domfer"]))
                k[4].metric("Subtotal", brl(p_valor))

                pessoas.append({**p, **pt, "linhas": linhas, "tot_horas": ph, "total": p_valor})
                for t in TIPOS:
                    tot[t] += pt[t]
                g_total += p_valor

        d.update({"pessoas": pessoas, "tot": tot, "subtotais": subtotais,
                  "tot_horas": sum(tot.values()), "total": g_total})

        st.divider()
        st.markdown("### 📊 Resumo geral")
        if pessoas:
            st.dataframe(pd.DataFrame([{
                "Pessoa": p["nome"], "Função": p["funcao"],
                "Base": brl(p["valor_hora"]), "Comercial": hhmm(p["comercial"]),
                "Extra útil": hhmm(p["extra_util"]), "Sábado": hhmm(p["sabado"]),
                "Dom/Fer": hhmm(p["domfer"]), "Total": hhmm(p["tot_horas"]),
                "Subtotal": brl(p["total"]),
            } for p in pessoas]), use_container_width=True, hide_index=True)

            st.dataframe(pd.DataFrame([{
                "TIPO DE HORA": ROTULOS[t], "TOTAL DE HORAS": hhmm(tot[t]),
                "VALOR (R$/h)": "variável" if d["multi_base"] else brl(tf0[t]),
                "SUBTOTAL": brl(subtotais[t]),
            } for t in TIPOS if tot[t] > 0]), use_container_width=True, hide_index=True)

        r = st.columns(3)
        r[0].metric("Pessoas", len(pessoas))
        r[1].metric("Total de horas", hhmm(sum(tot.values())))
        r[2].metric("VALOR TOTAL", brl(g_total))
    else:
        d.update({"pessoas": [], "tot": {t: 0.0 for t in TIPOS},
                  "subtotais": {t: 0.0 for t in TIPOS}, "tot_horas": 0, "total": 0})

st.divider()
d["observacoes"] = st.text_area("Observações (opcional)")

if st.button("📥 Gerar orçamento em PDF", type="primary"):
    if not empresa_nome or empresa_nome == "-":
        st.error("Defina a empresa que você está representando.")
    elif d["modo"] == "horas" and not d.get("pessoas"):
        st.error("Cadastre ao menos uma pessoa e lance os horários.")
    else:
        st.success("Orçamento gerado com sucesso!")
        st.download_button("⬇️ Baixar PDF", data=gerar_pdf(d),
                           file_name=f"orcamento_{d['numero']}.pdf", mime="application/pdf")
