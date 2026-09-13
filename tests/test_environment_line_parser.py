"""Environment repair accepts an explicit catalog without runtime setup."""

from superforecasting_agent.configuration.env_lines import sanitize_env_lines


def test_overlapping_keys_do_not_split_inside_longer_name():
    assert sanitize_env_lines(['GLM_API_KEY=firstOPENAI_API_KEY=second\n'],
                              {'LM_API_KEY', 'GLM_API_KEY', 'OPENAI_API_KEY'}) == [
        'GLM_API_KEY=first\n', 'OPENAI_API_KEY=second\n',
    ]


def test_unknown_key_like_text_and_comments_are_preserved():
    lines = ['# café\r\n', '\r\n', 'MODEL=vendor/UNKNOWN_NAME=value\n']
    assert sanitize_env_lines(lines, {'MODEL'}) == [
        '# café\n', '\n', 'MODEL=vendor/UNKNOWN_NAME=value\n',
    ]


def test_catalog_is_an_input_not_global_configuration():
    line = ['FIRST=aSECOND=b']
    assert sanitize_env_lines(line, {'FIRST'}) == ['FIRST=aSECOND=b\n']
    assert sanitize_env_lines(line, {'FIRST', 'SECOND'}) == ['FIRST=a\n', 'SECOND=b\n']
