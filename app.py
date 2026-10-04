import os
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = "snap-pantry-secret-key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "pantry.db")

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"


# ---------- Database ----------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            mfg_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            price REAL NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


# ---------- Core logic: expiry + automatic discount ----------
def get_status(expiry_str, price):
    """Discount is calculated every time from today's date, not stored."""
    days_left = (date.fromisoformat(expiry_str) - date.today()).days
    if days_left < 0:
        return days_left, "EXPIRED", 0, 0.0
    if days_left <= 1:          # 1 day (or expiring today) -> 50%
        return days_left, "SNAP", 50, round(price * 0.5, 2)
    if days_left <= 2:          # 2 days -> 20%
        return days_left, "SNAP", 20, round(price * 0.8, 2)
    return days_left, "NORMAL", 0, price


def load_products():
    conn = get_db()
    rows = conn.execute("SELECT * FROM products ORDER BY expiry_date").fetchall()
    conn.close()
    products = []
    for r in rows:
        days_left, status, discount, final_price = get_status(r["expiry_date"], r["price"])
        p = dict(r)
        p.update(days_left=days_left, status=status, discount=discount, final_price=final_price)
        products.append(p)
    return products


# ---------- Login ----------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Wrong username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("snap_pantry"))


# ---------- Pages ----------
@app.route("/")
def home():
    return redirect(url_for("snap_pantry"))


@app.route("/snap")
def snap_pantry():
    items = [p for p in load_products() if p["status"] == "SNAP" and p["quantity"] > 0]
    items.sort(key=lambda p: (-p["discount"], p["name"]))
    return render_template("snap_pantry.html", items=items)


@app.route("/admin")
@login_required
def admin():
    products = load_products()
    expiring = [p for p in products if p["status"] == "SNAP"]
    expired = [p for p in products if p["status"] == "EXPIRED"]
    return render_template("admin.html", products=products, expiring=expiring, expired=expired)


def read_form():
    return (
        request.form["name"].strip(),
        int(request.form["quantity"]),
        request.form["mfg_date"],
        request.form["expiry_date"],
        float(request.form["price"]),
    )


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        name, qty, mfg, exp, price = read_form()
        if exp < mfg:
            flash("Expiry date cannot be before manufacturing date.", "danger")
            return render_template("product_form.html", product=request.form, title="Add Product")
        conn = get_db()
        conn.execute(
            "INSERT INTO products (name, quantity, mfg_date, expiry_date, price) VALUES (?,?,?,?,?)",
            (name, qty, mfg, exp, price),
        )
        conn.commit()
        conn.close()
        flash("Product added.", "success")
        return redirect(url_for("admin"))
    return render_template("product_form.html", product={}, title="Add Product")


@app.route("/edit/<int:pid>", methods=["GET", "POST"])
@login_required
def edit_product(pid):
    conn = get_db()
    if request.method == "POST":
        name, qty, mfg, exp, price = read_form()
        if exp < mfg:
            flash("Expiry date cannot be before manufacturing date.", "danger")
            conn.close()
            return render_template("product_form.html", product=request.form, title="Edit Product")
        conn.execute(
            "UPDATE products SET name=?, quantity=?, mfg_date=?, expiry_date=?, price=? WHERE id=?",
            (name, qty, mfg, exp, price, pid),
        )
        conn.commit()
        conn.close()
        flash("Product updated.", "success")
        return redirect(url_for("admin"))
    product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    if product is None:
        return redirect(url_for("admin"))
    return render_template("product_form.html", product=dict(product), title="Edit Product")


@app.route("/delete/<int:pid>", methods=["POST"])
@login_required
def delete_product(pid):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash("Product deleted.", "info")
    return redirect(url_for("admin"))


@app.route("/seed")
@login_required
def seed():
    """Adds sample products so you can test every case quickly."""
    today = date.today()
    samples = [
        ("Milk 1L", 20, -5, 1, 56),
        ("Curd 500g", 15, -4, 2, 40),
        ("Bread", 30, -3, 1, 35),
        ("Paneer 200g", 10, -6, 2, 90),
        ("Butter 100g", 25, -20, 10, 58),
        ("Rice 5kg", 40, -60, 200, 420),
        ("Biscuits", 50, -30, 90, 20),
        ("Old Yogurt", 5, -15, -2, 30),
        ("Cheese Slices", 12, -10, 0, 120),
        ("Cake", 8, -2, 2, 250),
    ]
    conn = get_db()
    for name, qty, mfg_off, exp_off, price in samples:
        conn.execute(
            "INSERT INTO products (name, quantity, mfg_date, expiry_date, price) VALUES (?,?,?,?,?)",
            (name, qty, (today + timedelta(days=mfg_off)).isoformat(),
             (today + timedelta(days=exp_off)).isoformat(), price),
        )
    conn.commit()
    conn.close()
    flash("Sample products added.", "success")
    return redirect(url_for("admin"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
