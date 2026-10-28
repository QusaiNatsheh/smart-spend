# Smart Spend: demo video script

Length: about 60 seconds. Format: MP4, 1920×1080 (a square 1080×1080 cut also works for the LinkedIn feed).
Use only real screens: record the app, or animate the files in `docs/screenshots/`. Do not redraw any screen or
change any number.

Before recording: `make demo`, then start the app with the local model
(`AI_PROVIDER=ollama OLLAMA_URL=http://localhost:11434 python manage.py runserver`), and log in as
demo@smartspend.app / demo1234. The local model takes 10–15 seconds per answer, so cut the waiting in editing.

| # | Time | Screen (screenshot) | Action on screen | Voice-over / caption |
|---|---|---|---|---|
| 1 | 0–4 s | Title card | "Smart Spend" · "Personal finance that explains itself" | — |
| 2 | 4–12 s | Dashboard (`01_dashboard.png`) | Slow zoom on the budget bar and the month-end forecast | "One look: balance, budget used, and where the month will end at today's pace." |
| 3 | 12–22 s | Quick add (`02_ai_quick_add.png`) | Type "Paid 18.50 for shawarma with friends yesterday", click *Add with AI*; the row appears | "Type one sentence. AI fills in the title, amount, category and date." |
| 4 | 22–32 s | Chat (`03_chat.png`) | Ask "What are my top 3 spending categories this month?" | "Ask about your money. This runs on a free local model, so the data stays on the machine." |
| 5 | 32–42 s | Insights (`04_insights.png`) | Zoom on "8.6x your usual Restaurant", then on the monthly bills list | "No AI needed here. It flags what is unusual for that merchant, and finds every monthly bill." |
| 6 | 42–49 s | Transactions (`05_transactions_filtered.png`) | Filter by Dining; show the total | "Search, filter, and export exactly what you see." |
| 7 | 49–55 s | Report (`06_monthly_report.png`) | Zoom on savings rate and the category bars | "Every month: income, spending and savings rate." |
| 8 | 55–60 s | End card | "Django 6 · Gemini or local Ollama · 48 tests · Docker" · "github.com/QusaiNatsheh/smart-spend" | — |

Optional extra shot (5 s, between 6 and 7): the CSV import error box (`07_import_validation.png`), caption
"Bad file? Nothing is imported, and every problem is listed by line."

## Captions only (for a silent video)
1. Smart Spend: personal finance that explains itself
2. Budget, balance and month-end forecast at a glance
3. One sentence → a categorized expense
4. Chat with your spending, on a free local model
5. Unusual expenses and monthly bills, found without AI
6. Search, filter, export
7. Monthly report with savings rate
8. Django 6 · Gemini or local Ollama · 48 tests · Docker
