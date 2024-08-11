from flask import Flask, render_template, request, redirect, url_for, flash, session as flask_session
import os
from functools import wraps
import json
import smtplib
import csv
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, storage
from datetime import timedelta, datetime
import pytz
from hashlib import sha256

load_dotenv()
active_sessions = {}
sender = os.getenv('sender')
password = os.getenv('password')
admin_mail = os.getenv('admin')
password_admin = os.getenv('password_admin')
app = Flask(__name__)
app.secret_key = 'your_secret_key'
CREDENTIALS_URL = os.getenv('CREDENTIALS_URL')
RESULTS_URL = os.getenv('RESULTS_URL')
ENSA_STUDENTS_URL = os.getenv('ENSA_STUDENTS_URL')
LOGS = os.getenv('LOGS')
service_account_key = json.loads(os.getenv('SERVICE_ACCOUNT_KEY'))

# Initialize Firebase Admin
cred = credentials.Certificate(service_account_key)
firebase_admin.initialize_app(cred, {
    'storageBucket': 'votingplatform-4edce.appspot.com'
})

# Set session lifetime to 15 minutes
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)

def read_credentials():
    response = requests.get(CREDENTIALS_URL)
    if response.status_code == 200:
        credentials = {}
        for line in response.text.splitlines():
            email, password, status = line.strip().split(',')
            credentials[email] = (password, int(status))
        return credentials
    else:
        return {}


def read_results():
    response = requests.get(RESULTS_URL)
    if response.status_code == 200:
        results = {line.split(',')[0]: int(line.split(',')[1]) for line in response.text.splitlines()}
        choices = ["Novators", "Clavis", "Achievers"]
        for choice in choices:
            if choice not in results:
                results[choice] = 0
        return results
    else:
        return {"Novators": 0, "Clavis": 0, "Achievers": 0}

def update_results_file(results):
    results_text = "\n".join([f"{choice},{count}" for choice, count in results.items()])
    bucket = storage.bucket()
    blob = bucket.blob('.results.txt')
    blob.upload_from_string(results_text)

def update_credentials_file(credentials):
    credentials_text = "\n".join([f"{email},{data[0]},{data[1]}" for email, data in credentials.items()])
    bucket = storage.bucket()
    blob = bucket.blob('.credentials.txt')
    blob.upload_from_string(credentials_text)

def send_email(subject, recipient, body):
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Error: {e}")

def log_action(action, first_name=None, last_name=None, email=None, ip_address=None, action_details=None):
    log_entry = f"{datetime.now(pytz.timezone('Europe/Paris')).isoformat()}.\n\tAction: {action}\n\t"
    
    if first_name and last_name:
        log_entry += f"Name: {first_name} {last_name}\n\t"
    
    if email:
        log_entry += f"Email: {email}\n\t"
    
    if ip_address:
        log_entry += f"IP: {ip_address}\n\t"
    
    if action_details:
        log_entry += f"Voted to: {action_details}.\n"
    
    # Append the log entry to the log file
    bucket = storage.bucket()
    blob = bucket.blob('logs.txt')
    current_logs = blob.download_as_text() if blob.exists() else ''
    blob.upload_from_string(current_logs + log_entry + '\n', content_type='text/plain')

def get_ip_address():
    return request.remote_addr  # Get the IP address of the requester

def checktime():
    start_time = datetime(2024, 8, 11, 10, 0, 0, tzinfo=pytz.timezone('Europe/Paris'))
    end_time = datetime(2024, 8, 12, 9, 0, 0, tzinfo=pytz.timezone('Europe/Paris'))
    current_time = datetime.now(pytz.timezone('Europe/Paris'))
    return start_time <= current_time < end_time

# Add this decorator to routes that need login protection
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in_email' not in flask_session:
            flash('You need to log in first.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.after_request
def add_header(response):
    # Prevent caching of pages by the browser
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/')
def index():
    
    log_action("Someone Logged In", ip_address=get_ip_address())
    if checktime():
        return redirect(url_for('register'))
    else:
        return render_template('countdown.html')

def load_students_data():
    students_data = []
    response = requests.get(ENSA_STUDENTS_URL)
    if response.status_code == 200:
        lines = response.text.splitlines()
        reader = csv.reader(lines)
        for row in reader:
            students_data.append(row)
    return students_data

def check_student_exists(first_name, last_name, students_data):
    normalized_first_name = first_name.strip().lower().replace(" ", "").replace("-", "")
    normalized_last_name = last_name.strip().lower().replace(" ", "").replace("-", "")
    for student in students_data:
        if student and len(student) >= 2:
            if student[0].strip().lower().replace(" ", "").replace("-", "") == normalized_first_name and \
               student[1].strip().lower().replace(" ", "").replace("-", "") == normalized_last_name:
                return True
    return False

@app.route('/register', methods=['GET', 'POST'])
def register():
    if checktime():
        students_data = load_students_data()
        if request.method == 'POST':
            first_name = request.form['first_name'].lower()
            last_name = request.form['last_name'].lower()
            is_new_student = request.form['is_new_student']

            # Log action right after registration starts
            log_action("Start Registration", first_name, last_name, ip_address=get_ip_address())
            
            if not check_student_exists(first_name, last_name, students_data):
                flash('You entered your data wrong, or you aren\'t an ENSA student. Please contact the admins through the contact us page.', 'danger')
                return redirect(url_for('register'))

            first_name = first_name.replace(" ", "").replace("-", "")
            last_name = last_name.replace(" ", "").replace("-", "")
            email = f"{first_name.lower()}.{last_name.lower()}.23@edu.uiz.ac.ma" if is_new_student == "yes" else f"{first_name.lower()}.{last_name.lower()}@edu.uiz.ac.ma"
            credentials = read_credentials()

            if email in credentials:
                flash('This email already exists. If it seems wrong, contact the admins', 'danger')
                return redirect(url_for('register'))

            hashed_password = sha256(email.encode()).hexdigest()[:8]
            new_credential = (hashed_password, 0)
            subject = "Welcome to the Voting Platform"
            body = f"Hello {first_name},\n\nYour account has been created. Here is your login information:\n\nEmail: {email}\nPassword: {hashed_password}\n\nPlease log in to cast your vote."
            send_email(subject, email, body)

            credentials[email] = new_credential
            update_credentials_file(credentials)
            flash('Registration successful! Please check your email for login details.', 'success')
            return redirect(url_for('login'))

        return render_template('register.html')
    else:
        return render_template('countdown.html')

@app.route('/admin', methods=['GET'])
def admin():
    if 'logged_in_email' not in flask_session or flask_session['logged_in_email'] != admin_mail:
        flash('Access denied. Admins only.')
        return redirect(url_for('login'))

    results = read_results()
    return render_template('admin.html', results=results)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if checktime():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            credentials = read_credentials()

            # Check if the email exists in the credentials file
            if email not in credentials or credentials[email][0] != password:
                flash('Invalid email or password.', 'danger')
                return redirect(url_for('login'))


            # If everything is fine, log in the user and redirect to the vote page
            flask_session['logged_in_email'] = email
            active_sessions[email] = True
            if email == admin_mail and password == password_admin:
                return redirect(url_for('admin'))

            # Check if the user has already voted
            if credentials[email][1] == 1 :
                flash('You have already voted.\n If this is an error, please contact the admins.', 'danger')
                return redirect(url_for('login'))
            flash('Login successful!', 'success')
            return redirect(url_for('vote', email=email))

        return render_template('login.html')
    else:
        return render_template('countdown.html')

@app.route('/vote/<email>', methods=['GET', 'POST'])
@login_required
def vote(email):
    credentials = read_credentials()

    if request.method == 'POST':
        selected_choice = request.form['choice']
        results = read_results()

        if selected_choice in results:
            results[selected_choice] += 1
            update_results_file(results)

            # Mark the email as having voted in the credentials
            credentials[email] = (credentials[email][0], 1)  # Update voting status to indicate voted
            update_credentials_file(credentials)

            # Log the vote action with the selected choice
            log_action("Vote", email=email, ip_address=get_ip_address(), action_details=selected_choice)
            content = f'{email} voted for {selected_choice}.'
            send_email('Vote', email, content)
            flash('Vote successfully recorded!', 'success')
            return redirect(url_for('logout'))
        else:
            flash('Invalid choice. Please try again.', 'danger')
            return redirect(url_for('vote', email=email))

    return render_template('vote.html', email=email)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', error_code=404, error_message="Sorry, the page you are looking for does not exist."), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html', error_code=500, error_message="An internal server error occurred. Please try again later."), 500


@app.route('/logout', methods=['GET'])
def logout():
    flask_session.pop('logged_in_email', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if checktime():
            
        if request.method == 'POST':
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            class_ = request.form['class']
            issue = request.form['subject']
            message = request.form['message']
            tel = request.form['num']
            email = f"Issue: {issue}\n\tStudent: {first_name} {last_name}\n\tClass: {class_}\n\tPhone: {tel}\n\tMessage: {message}"
            log_action("Contact Form Submitted", first_name=first_name, last_name=last_name, email=email, ip_address=get_ip_address())
            flash('Your message has been sent!', 'success')
            return redirect(url_for('contact'))

        return render_template('contact.html')
    else:
        return render_template('countdown.html')



if __name__ == '__main__':
    app.run(debug=True)
