import pandas as pd
from utils.cosif_view import compact_table, period_label, account_label


def test_compact_cosif_table_preserves_signs_missing_values_and_units():
    rank = pd.DataFrame({'Ranking': [1, 2], 'Instituição': ['A', 'B'],
                         'Valor 202606': [-13_300_000., None], 'Valor 202603': [-10_000_000., 0],
                         'Variação': [-3_300_000., None], 'Variação %': [-33., None],
                         '% do Total Exibido': [100., 0.]})
    before = rank.copy()
    view = compact_table(rank, ['202606', '202603'])
    assert view['Jun/26 (R$ mi)'].tolist() == ['-13,3', 'N/D']
    assert view['Mar/26 (R$ mi)'].tolist() == ['-10,0', '0,0']
    assert view['Variação (%)'].tolist() == ['-33,0%', 'N/D']
    assert len(view.columns) == 7
    pd.testing.assert_frame_equal(rank, before)


def test_cosif_labels_use_month_and_name_before_code():
    assert period_label('202512') == 'Dez/25'
    assert period_label('202607') == 'Jul/26'
    assert account_label('8118500009', '8118500009 | DESPESAS') == 'DESPESAS · 8118500009'
