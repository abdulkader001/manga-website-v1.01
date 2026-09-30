from typing import Optional, List
from sqlalchemy.orm import Session
from ..models import ScrapingJob


class ScrapingJobRepository:
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_by_id(self, job_id: int) -> Optional[ScrapingJob]:
        return self.db.query(ScrapingJob).filter(ScrapingJob.id == job_id).first()

    def get_queued_jobs(self) -> List[ScrapingJob]:
        return self.db.query(ScrapingJob).filter(ScrapingJob.status == "queued").all()

    def mark_in_progress(self, job: ScrapingJob) -> ScrapingJob:
        job.status = "in_progress"
        self.db.flush()
        return job

    def mark_success(self, job: ScrapingJob) -> ScrapingJob:
        job.status = "success"
        self.db.flush()
        return job

    def mark_failed(self, job: ScrapingJob, error_msg: str) -> ScrapingJob:
        job.status = "failed"
        job.error = error_msg
        self.db.flush()
        return job

    def update(self, job: ScrapingJob, **kwargs) -> ScrapingJob:
        for key, value in kwargs.items():
            setattr(job, key, value)
        self.db.flush()
        return job
