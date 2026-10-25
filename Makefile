.PHONY: setup api seed test eval web apk clean

setup:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

api:            ## run the API (serves the built web apps at /, /teacher/, /parent/)
	cd backend && .venv/bin/uvicorn app.main:app --reload

seed:           ## reset the demo school
	rm -f backend/kaksha_dev.db
	cd backend && .venv/bin/python -m app.seed

test:
	cd backend && .venv/bin/python -m pytest -q

eval:           ## deterministic evals (no API key)
	cd backend && .venv/bin/python ../evals/run_extraction.py --mode rules
	cd backend && .venv/bin/python ../evals/run_planner.py
	cd backend && .venv/bin/python ../evals/run_scorer.py

web:            ## rebuild both Flutter web apps into deploy/web
	cd apps/teacher && flutter build web --release --base-href /teacher/ \
	  && rsync -a --delete build/web/ ../../deploy/web/teacher/
	cd apps/parent && flutter build web --release --base-href /parent/ \
	  && rsync -a --delete build/web/ ../../deploy/web/parent/

apk:
	cd apps/teacher && flutter build apk --release
	cd apps/parent && flutter build apk --release

clean:
	rm -rf backend/uploads backend/kaksha_dev.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
