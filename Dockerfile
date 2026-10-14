FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/munimtechnologies/dbgap-cohort-finder" \
      org.opencontainers.image.description="Rank public dbGaP studies for cohort-feasibility questions" \
      org.opencontainers.image.licenses="Apache-2.0"
WORKDIR /app
COPY cohort_finder.py /app/cohort_finder.py
WORKDIR /data
ENTRYPOINT ["python", "/app/cohort_finder.py"]
CMD ["--help"]
