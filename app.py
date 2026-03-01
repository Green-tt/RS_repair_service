import sqlite3
from flask import Flask, render_template, request, redirect, session, g, abort
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret"

DATABASE = "database.sqlite"


# ================= DB =================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        role TEXT
    );

    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clientName TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT NOT NULL,
        problemText TEXT NOT NULL,
        status TEXT NOT NULL,
        assignedTo INTEGER,
        createdAt TEXT,
        updatedAt TEXT
    );
    """)

    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        db.execute("INSERT INTO users (name, role) VALUES ('dispatcher', 'dispatcher')")
        db.execute("INSERT INTO users (name, role) VALUES ('master1', 'master')")
        db.execute("INSERT INTO users (name, role) VALUES ('master2', 'master')")
        db.commit()

    db.close()


init_db()

# ================= AUTH =================
@app.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()
    if request.method == "POST":
        session["user_id"] = request.form["user_id"]
        return redirect("/")

    users = db.execute("SELECT * FROM users").fetchall()
    return render_template("login.html", users=users)


@app.before_request
def load_user():
    if request.endpoint == "login":
        return
    if "user_id" not in session:
        return redirect("/login")
    db = get_db()
    g.user = db.execute("SELECT * FROM users WHERE id=?",
                        (session["user_id"],)).fetchone()

@app.context_processor
def inject_user():
    return dict(g=g)


@app.route("/")
def home():
    if g.user["role"] == "dispatcher":
        return redirect("/dispatcher")
    if g.user["role"] == "master":
        return redirect("/master")


# ================= CREATE REQUEST =================
@app.route("/requests/new")
def new_request():
    return render_template("new.html")


@app.route("/requests", methods=["POST"])
def create_request():
    db = get_db()
    now = datetime.utcnow().isoformat()

    db.execute("""
        INSERT INTO requests
        (clientName, phone, address, problemText, status, createdAt, updatedAt)
        VALUES (?, ?, ?, ?, 'new', ?, ?)
    """, (
        request.form["clientName"],
        request.form["phone"],
        request.form["address"],
        request.form["problemText"],
        now,
        now
    ))
    db.commit()
    return redirect("/dispatcher")


# ================= DISPATCHER =================
@app.route("/dispatcher")
def dispatcher():
    db = get_db()
    status = request.args.get("status")

    if status:
        requests = db.execute(
            "SELECT * FROM requests WHERE status=?", (status,)
        ).fetchall()
    else:
        requests = db.execute("SELECT * FROM requests").fetchall()

    masters = db.execute(
        "SELECT * FROM users WHERE role='master'"
    ).fetchall()

    return render_template("dispatcher.html",
                           requests=requests,
                           masters=masters)


@app.route("/requests/<int:id>/assign", methods=["POST"])
def assign(id):
    db = get_db()
    db.execute("""
        UPDATE requests
        SET status='assigned', assignedTo=?, updatedAt=?
        WHERE id=?
    """, (request.form["master_id"],
          datetime.utcnow().isoformat(),
          id))
    db.commit()
    return redirect("/dispatcher")


@app.route("/requests/<int:id>/cancel", methods=["POST"])
def cancel(id):
    db = get_db()
    db.execute("""
        UPDATE requests
        SET status='canceled', updatedAt=?
        WHERE id=?
    """, (datetime.utcnow().isoformat(), id))
    db.commit()
    return redirect("/dispatcher")


# ================= MASTER =================
@app.route("/master")
def master():
    db = get_db()
    requests = db.execute("""
        SELECT * FROM requests
        WHERE assignedTo=?
    """, (g.user["id"],)).fetchall()

    return render_template("master.html", requests=requests)


# 🔥 SAFE TAKE (race condition safe)
@app.route("/requests/<int:id>/take", methods=["POST"])
def take(id):
    db = get_db()

    result = db.execute("""
        UPDATE requests
        SET status='in_progress', updatedAt=?
        WHERE id=? AND status='assigned'
    """, (datetime.utcnow().isoformat(), id))

    db.commit()

    if result.rowcount == 0:
        abort(409, "Already taken")

    return "OK"


@app.route("/requests/<int:id>/done", methods=["POST"])
def done(id):
    db = get_db()
    db.execute("""
        UPDATE requests
        SET status='done', updatedAt=?
        WHERE id=? AND status='in_progress'
    """, (datetime.utcnow().isoformat(), id))
    db.commit()
    return redirect("/master")


if __name__ == "__main__":
    app.run(debug=True)