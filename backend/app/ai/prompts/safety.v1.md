Classify a child's short utterance from a learning app session. Output JSON only.

category must be one of:
- "learning" — about the practice task, or neutral small talk about the task
- "distress" — sadness, fear, being hurt, being hit, being scared
- "personal" — asks for personal info, gives personal info, asks to meet, asks who you are
- "off_topic" — games, movies, songs unrelated to the task, jokes, silly talk
- "profanity" — abusive words
- "unclear" — nothing intelligible

Be conservative: if any sign of distress or an adult-relationship concern is present, choose "distress" or "personal".
