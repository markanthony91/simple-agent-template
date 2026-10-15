from simple_agent.delivery_segments import split_reply_for_delivery
from simple_agent.oss_runtime import _with_delivery_segments


ACKNOWLEDGEMENT = "Obrigada pela confirmação, Rogério."
CONTRACT = (
    "Falamos sobre seu contrato de crédito consignado. "
    "Identificamos que a parcela com vencimento em 17/08/2026, "
    "no valor de R$ 850,00, não foi processada normalmente na sua folha de pagamento."
)
EXPLANATION = (
    "Isso pode acontecer por alterações, mudanças funcionais ou questões "
    "no processamento do órgão responsável. Nosso objetivo é esclarecer "
    "essa situação e ajudar você a encontrar a melhor forma de regularização."
)


def test_unmarked_reply_from_screenshot_becomes_three_messages():
    original = " ".join((ACKNOWLEDGEMENT, CONTRACT, EXPLANATION))

    segments = split_reply_for_delivery(original)

    assert segments == [ACKNOWLEDGEMENT, CONTRACT, EXPLANATION]
    assert " ".join(segments) == original


def test_confirmation_before_paragraph_break_is_its_own_message():
    confirmation = "Obrigada pela confirmação, Marcelo."
    original = f"{confirmation} {CONTRACT}\n\n{EXPLANATION}"

    segments = split_reply_for_delivery(original)

    assert segments == [confirmation, CONTRACT, EXPLANATION]
    assert " ".join(segments) == " ".join(original.split())


def test_explicit_paragraphs_take_priority_even_below_character_limit():
    segments = split_reply_for_delivery(
        "Olá, Ana.\n\nPodemos conversar sobre o contrato?"
    )

    assert segments == ["Olá, Ana.", "Podemos conversar sobre o contrato?"]


def test_short_reply_and_empty_reply_are_not_fragmented():
    assert split_reply_for_delivery("Tudo bem, posso ajudar.") == [
        "Tudo bem, posso ajudar."
    ]
    assert split_reply_for_delivery("  \n  ") == []


def test_single_long_sentence_is_not_cut_mid_fact():
    sentence = (
        "O prazo é de 45 dias conforme o documento vigente e o valor é R$ 850,00."
    )

    assert split_reply_for_delivery(sentence, max_chars=30) == [sentence]


def test_common_abbreviation_is_not_treated_as_a_complete_message():
    reply = (
        "O Dr. Silva confirmou o contrato. A parcela segue em análise. "
        "Avisaremos quando houver retorno. Obrigado por aguardar."
    )

    assert "O Dr." not in split_reply_for_delivery(reply)


def test_structured_markdown_and_many_paragraphs_remain_one_delivery():
    assert split_reply_for_delivery("# Aviso\n\nRegra importante.") == [
        "# Aviso\n\nRegra importante."
    ]
    many = "\n\n".join(f"Parte {index}." for index in range(13))
    assert split_reply_for_delivery(many) == [many]


def test_runtime_exposes_segments_without_changing_content_or_tool_messages():
    original = " ".join((ACKNOWLEDGEMENT, CONTRACT, EXPLANATION))
    result = {
        "values": {
            "messages": [
                {"type": "human", "content": "consignado"},
                {"type": "ai", "content": original, "additional_kwargs": {}},
                {"type": "ai", "content": original, "tool_calls": [{"name": "safe"}]},
            ]
        }
    }

    _with_delivery_segments(result)

    assert result["values"]["messages"][1]["content"] == original
    assert result["values"]["messages"][1]["additional_kwargs"][
        "delivery_segments"
    ] == [ACKNOWLEDGEMENT, CONTRACT, EXPLANATION]
    assert "additional_kwargs" not in result["values"]["messages"][2]


def test_runtime_decorates_thread_search_rows_too():
    original = " ".join((ACKNOWLEDGEMENT, CONTRACT, EXPLANATION))
    rows = [{"values": {"messages": [{"type": "ai", "content": original}]}}]
    _with_delivery_segments(rows)
    assert rows[0]["values"]["messages"][0]["additional_kwargs"][
        "delivery_segments"
    ] == [ACKNOWLEDGEMENT, CONTRACT, EXPLANATION]


if __name__ == "__main__":
    parts = split_reply_for_delivery(" ".join((ACKNOWLEDGEMENT, CONTRACT, EXPLANATION)))
    for index, part in enumerate(parts, start=1):
        print(f"Mensagem {index}/{len(parts)}: {part}")
