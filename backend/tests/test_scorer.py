from app.speech.scorer import normalize, score_read


def test_exact_words_correct():
    r = score_read(["कमल", "घर"], "कमल घर")
    assert r.n_correct == 2 and r.accuracy == 1.0


def test_letter_order_is_close_not_correct():
    r = score_read(["कमल"], "कलम")
    assert r.items[0].judged == "close"
    assert "कमल" in r.items[0].note_hi  # tells the teacher which word was expected


def test_number_digits_and_words():
    assert score_read(["12"], "बारह").n_correct == 1
    assert score_read(["12"], "12").n_correct == 1
    assert score_read(["52"], "पचास").n_wrong == 1


def test_omission_detected_when_transcript_ends():
    r = score_read(["का", "कि", "की"], "का कि")
    assert r.n_omitted == 1
    assert r.items[-1].judged == "omitted"


def test_spoken_but_different_is_wrong_not_omitted():
    r = score_read(["का", "कि"], "का कु")
    assert r.items[1].judged == "wrong"


def test_sequence_does_not_swallow_rest_after_a_miss():
    # regression: a later token used to out-score the in-order one and eat the rest
    r = score_read(["कमल", "घर", "कल"], "कलम घर कल")
    assert [i.judged for i in r.items] == ["close", "correct", "correct"]
    assert r.n_omitted == 0


def test_fillers_removed():
    assert normalize("हम्म कमल।") == ["कमल"]


def test_devanagari_digits():
    assert score_read(["52"], "५२").n_correct == 1


def test_empty_transcript_all_omitted():
    r = score_read(["52 − 28 कितना", "कमल"], "")
    assert r.n_omitted == 2


def test_phrase_reading():
    r = score_read(["राम का घर"], "राम का घर")
    assert r.n_correct == 1
    r2 = score_read(["राम का घर"], "राम घर")
    assert r2.items[0].judged != "correct"
