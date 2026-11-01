# Sample inputs: five things to try

These are the inputs we used most while building and testing Kaksha Saathi. Each one takes under two
minutes. All children in the demo school are fictional.

**Logins**
- Teacher: school code `DEMO`, PIN `1234`
- Parent: school code `DEMO`, roll number `12`, phone `9876500000`, PIN `0000` (child: कविता, class 2A)

Web: https://kaksha-saathi-558g.onrender.com/teacher/ and https://kaksha-saathi-558g.onrender.com/parent/
(the first load after a quiet spell can take up to a minute while the free server wakes up).

---

## 1. Teacher: an end-of-day voice note in Hindi

1. Log in as the teacher and open **कक्षा 2A**, subject **Maths**.
2. Tap **Add evidence**, then **Voice**. Speak, or type into the box:

   > आज उधार वाला घटाव कराया। मीना को उधार समझ नहीं आया। अर्जुन ने सही किया। प्रिया नहीं आई।

   Mixed Hindi and English works too, for example:
   "Aaj borrowing wala subtraction karaya. Arjun ne sahi kiya, Meena ko borrow karne mein dikkat aayi."
3. Tap **Understand**.

**What you should see:** one card per child (मीना: Wrong, अर्जुन: Correct, प्रिया: absent), each with
the exact words it came from and the lesson "2-digit subtraction with borrowing". Nothing is saved until
you tap **Confirm**. After confirming, the board's **Since yesterday** banner and the groups update.

## 2. Teacher: a photo of a notebook page, checked by code

1. Download `sample_notebook_page.png` (in this folder).
2. In **कक्षा 2A → Add evidence → Photo**, pick any child under **Whose work is this?**, then
   **Choose from gallery** and select the image.

**What you should see:** the AI reads all five sums. Code re-does the arithmetic, so `52 − 28 = 36` and
`63 − 27 = 46` come back **Wrong** (expected 24 and 36) and the other three **Correct**. You can change
any verdict before you **Confirm**: the teacher always has the final word.

## 3. Teacher: a quick tap check, then the same with no network

1. **Add evidence → Tap**, choose a lesson, tap **Mark everyone correct, then fix exceptions**, change one
   or two children to **Wrong** or **Partly**, then **Save**. No AI is used here.
2. Now switch on airplane mode (Android app) and reopen the class. The board still opens with
   "Offline: showing the last saved board".
3. Do another tap check and save it. The board shows **1 waiting to send**. Turn the network back on:
   it sends by itself and the board refreshes.

## 4. Parent: a voice practice session with Saathi

1. Log in to the parent app (roll `12`). Read **This week at school**, the catch-up activity and
   **Learning journey**.
2. Tap **Start voice session**, choose **हिन्दी**, and allow the microphone.
3. Saathi greets the child, warms up with joining sounds (पा + नी), then shows words such as हाथी,
   छतरी, मिठाई to read aloud. Read a few, get one wrong on purpose, then tap **Stop**.

**What you should see:** Saathi gives a hint and a retry when a word is misread. The **Session report**
shows right answers, first-try and after-retry counts, the exact sounds to practise, and the next focus.
Back in the teacher app (**कक्षा 2A → Hindi → कविता**), the session appears under **Voice sessions with
Saathi (home)**.

## 5. Teacher: set what Saathi practises at home

1. Teacher app → **कक्षा 2A → English** → tap **कविता**.
2. Under **Home practice focus**, tap **Change**, choose **Reading words**, add the note
   "Practise sh, ch, th words", keep **7 days**, then **Save**.
3. Open the parent app again and tap **Start voice session**.

**What you should see:** the **English** option now reads "Reading words (teacher-set focus)", and the
teacher's profile shows "Set by you until …". Tap **Back to automatic** to undo it.
