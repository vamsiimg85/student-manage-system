from __future__ import annotations

import os
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func, case


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///attendance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Student id={self.id} name={self.name!r} active={self.active}>"


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("student_id", "attendance_date", name="uq_student_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)  # "present" or "absent"
    marked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    student = db.relationship("Student", backref=db.backref("attendance", lazy=True))

    def __repr__(self) -> str:
        return (
            f"<Attendance id={self.id} student_id={self.student_id} "
            f"date={self.attendance_date} status={self.status}>"
        )


def parse_date_from_request(req: request) -> date:
    date_str = req.args.get("date") or req.form.get("date")
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


@app.before_first_request
def initialize_database() -> None:
    with app.app_context():
        db.create_all()


@app.route("/", methods=["GET"])  # Attendance form
def index():
    selected_date = parse_date_from_request(request)

    students = (
        Student.query.filter_by(active=True).order_by(Student.name.asc()).all()
    )

    # Existing attendance for the selected date
    existing = Attendance.query.filter_by(attendance_date=selected_date).all()
    attendance_by_student_id = {a.student_id: a for a in existing}

    return render_template(
        "index.html",
        students=students,
        selected_date=selected_date,
        attendance_by_student_id=attendance_by_student_id,
    )


@app.route("/submit", methods=["POST"])  # Save attendance
def submit_attendance():
    selected_date = parse_date_from_request(request)

    present_ids = set(map(int, request.form.getlist("present")))
    students = Student.query.filter_by(active=True).all()

    for student in students:
        status = "present" if student.id in present_ids else "absent"
        existing = Attendance.query.filter_by(
            student_id=student.id, attendance_date=selected_date
        ).first()
        if existing:
            existing.status = status
            existing.marked_at = datetime.utcnow()
        else:
            db.session.add(
                Attendance(
                    student_id=student.id,
                    attendance_date=selected_date,
                    status=status,
                )
            )

    db.session.commit()
    flash(f"Attendance saved for {selected_date.isoformat()}", "success")
    return redirect(url_for("index", date=selected_date.isoformat()))


@app.route("/students", methods=["GET"])  # Manage students
def students_page():
    students = Student.query.order_by(Student.active.desc(), Student.name.asc()).all()
    return render_template("students.html", students=students)


@app.route("/students/add", methods=["POST"])  # Add student
def add_student():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name is required", "danger")
        return redirect(url_for("students_page"))

    existing = Student.query.filter(func.lower(Student.name) == name.lower()).first()
    if existing:
        flash("Student already exists", "warning")
        return redirect(url_for("students_page"))

    db.session.add(Student(name=name, active=True))
    db.session.commit()
    flash("Student added", "success")
    return redirect(url_for("students_page"))


@app.route("/students/<int:student_id>/toggle", methods=["POST"])  # Activate/deactivate
def toggle_student(student_id: int):
    student = Student.query.get_or_404(student_id)
    student.active = not student.active
    db.session.commit()
    flash("Student status updated", "info")
    return redirect(url_for("students_page"))


@app.route("/attendance/history", methods=["GET"])  # Summary by date
def attendance_history():
    rows = (
        db.session.query(
            Attendance.attendance_date,
            func.sum(
                case((Attendance.status == "present", 1), else_=0)
            ).label("present_count"),
            func.count(Attendance.id).label("total_count"),
        )
        .group_by(Attendance.attendance_date)
        .order_by(Attendance.attendance_date.desc())
        .limit(60)
        .all()
    )

    return render_template("history.html", rows=rows)


@app.route("/attendance/<date_str>", methods=["GET"])  # Details for a day
def attendance_for_date(date_str: str):
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date", "danger")
        return redirect(url_for("attendance_history"))

    rows = (
        db.session.query(Student.name, Attendance.status)
        .join(Attendance, Attendance.student_id == Student.id)
        .filter(Attendance.attendance_date == selected_date)
        .order_by(Student.name.asc())
        .all()
    )
    return render_template(
        "attendance_detail.html", selected_date=selected_date, rows=rows
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)), debug=True)