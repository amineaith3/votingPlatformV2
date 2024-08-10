from flask import Flask, render_template, request, redirect, url_for, flash, session as flask_session
import os
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

sender = os.getenv('sender')
password = os.getenv('password')
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
        return [line.strip().split(',') for line in response.text.splitlines()]
    else:
        return []

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
    credentials_text = "\n".join([','.join(credential) for credential in credentials])
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
    start_time = datetime(2024, 8, 10, 21, 0, 0, tzinfo=pytz.timezone('Europe/Paris'))
    end_time = datetime(2024, 8, 12, 0, 0, 0, tzinfo=pytz.timezone('Europe/Paris'))
    current_time = datetime.now(pytz.timezone('Europe/Paris'))
    return start_time <= current_time < end_time

@app.route('/')
def index():
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

            if any(credential[0] == email for credential in credentials):
                flash('This email already exists.', 'danger')
                return redirect(url_for('register'))

            hashed_password = sha256(email.encode()).hexdigest()[:8]
            new_credential = [email, hashed_password, '0']
            subject = "Welcome to the Voting Platform"
            body = f"Hello {first_name},\n\nYour account has been created. Here is your login information:\n\nEmail: {email}\nPassword: {hashed_password}\n\nPlease log in to cast your vote."
            send_email(subject, email, body)

            credentials.append(new_credential)
            update_credentials_file(credentials)
            flash('Registration successful! Please check your email for login details.', 'success')
            return redirect(url_for('login'))

        return render_template('register.html')
    else:
        return render_template('countdown.html')

@app.route('/admin', methods=['GET'])
def admin():
    if 'logged_in_email' not in flask_session or flask_session['logged_in_email'] != sender:
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

            for credential in credentials:
                if credential[0] == email and credential[1] == password:
                    flask_session['logged_in_email'] = email
                    flash('Login successful!', 'success')
                    return redirect(url_for('vote'))

            flash('Invalid email or password.', 'danger')
            return redirect(url_for('login'))

        return render_template('login.html')
    else:
        return render_template('countdown.html')

@app.route('/vote', methods=['GET', 'POST'])
def vote():
    if 'logged_in_email' not in flask_session:
        flash('You need to log in first.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        selected_choice = request.form['choice']
        email = flask_session['logged_in_email']


        results = read_results()
        if selected_choice in results:
            results[selected_choice] += 1
            update_results_file(results)
             # Log the vote action with the selected choice
            log_action("Vote", email=email, ip_address=get_ip_address(), action_details=selected_choice)

            flash('Vote successfully recorded!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid choice. Please try again.', 'danger')
            return redirect(url_for('vote'))

    return render_template('vote.html')

@app.route('/logout', methods=['GET'])
def logout():
    flask_session.pop('logged_in_email', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        class_ = request.form['class']
        issue = request.form['issue']
        message = request.form['message']

        subject = issue
        email = f"Subject: {subject}, Email: {first_name} {last_name}, Message: \"the student {first_name} {last_name}, from class {class_}, is contacting \\n {message}\""
        
        # Log contact action
        log_action("Contact Form Submitted", first_name=first_name, last_name=last_name, email=email, ip_address=get_ip_address())

        # You can send an email here if required, similar to the send_email function above
        flash('Your message has been sent!', 'success')
        return redirect(url_for('contact'))

    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True)
