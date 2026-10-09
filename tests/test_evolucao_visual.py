import numpy as np
import pandas as pd

from utils.evolucao_visual import build_evolucao_chart, render_evolucao_table


def test_chart_preserves_original_series_and_missing_points_while_scaling_axes():
    original = pd.DataFrame({
        "Lucro Líquido": [-2e9, 4e9],
        "Patrimônio Líquido": [50e9, 60e9],
        "Carteira de Crédito*": [300e9, 350e9],
        "Core Funding*": [500e9, np.nan],
    })
    before = original.copy(deep=True)
    fig = build_evolucao_chart(original, ["dez-25", "jun-26"])
    assert [trace.type for trace in fig.data[:4]] == ["bar", "bar", "scatter", "scatter"]
    for trace, column in zip(fig.data[:4], original.columns):
        np.testing.assert_allclose(np.asarray(trace.y) * 1e9, original[column], equal_nan=True)
    pd.testing.assert_frame_equal(original, before)
    assert fig.layout.yaxis.range[0] < 0
    assert fig.data[-1].connectgaps is False
    assert "R$ bi" in fig.layout.yaxis.title.text
    assert "R$ bi" in fig.layout.yaxis2.title.text
    assert list(fig.layout.xaxis.ticktext) == ["Dez/25", "Jun/26"]
    for trace, label_trace in zip(fig.data[:4], fig.data[4:]):
        assert trace.legendgroup == label_trace.legendgroup
        assert label_trace.showlegend is False
        assert label_trace.hoverinfo == "skip"


def test_dense_history_prioritizes_last_available_data_and_dates_stale_series():
    original = pd.DataFrame({
        "Lucro Líquido": np.arange(1, 10) * 1e9,
        "Patrimônio Líquido": np.arange(21, 30) * 1e9,
        "Carteira de Crédito*": np.arange(101, 110) * 1e9,
        "Core Funding*": [*np.arange(201, 209) * 1e9, np.nan],
    })
    fig = build_evolucao_chart(original, [f"dez-{year}" for year in range(18, 27)])
    texts = [text for trace in fig.data[4:] for text in trace.text if text]
    assert len(texts) == 4
    assert all("<b>" in text for text in texts)
    stale = [text for text in texts if text.startswith("<b>208,0")]
    assert len(stale) == 1
    assert "Dez/25" in stale[0]
    assert fig.data[-1].textfont.color == fig.data[3].line.color


def test_table_keeps_analytical_markers_and_original_trace_tooltips():
    metric = "Índice de Capital Principal (CET1)"
    frame = pd.DataFrame([{"Métrica": metric, "dez-25": "-†", "jun-26": "12,3%"}])
    html = render_evolucao_table(
        frame, ["dez-25", "jun-26"],
        {(metric, "dez-25"): 'capital_report_missing: fonte <Rel. 5> "ausente"'},
        {metric: "Capital Principal ÷ RWA Total"},
    )
    assert 'scope="row"' in html
    assert "Capital Principal -CET1 (%)" in html
    assert ">-†</td>" in html
    assert ">12,3%</td>" in html
    assert "capital_report_missing" in html
    assert "&lt;Rel. 5&gt; &quot;ausente&quot;" in html
    assert ">Dez/25</th>" in html
