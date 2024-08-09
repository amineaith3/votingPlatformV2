from flask import Flask, render_template, request, redirect, url_for, flash, session as flask_session
import os
import json
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, storage
from datetime import timedelta
import time
from hashlib import sha256

load_dotenv()

sender = os.getenv('sender')
password = os.getenv('password')
app = Flask(__name__)
app.secret_key = 'your_secret_key'
CREDENTIALS_URL = os.getenv('CREDENTIALS_URL')
RESULTS_URL = os.getenv('RESULTS_URL')
service_account_key = json.loads(os.getenv('SERVICE_ACCOUNT_KEY'))

# Initialize Firebase Admin
cred = credentials.Certificate(service_account_key)
firebase_admin.initialize_app(cred, {
    'storageBucket': 'votingplatform-4edce.appspot.com'
})

# Set session lifetime to 15 minutes
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)

# Global session tracker to monitor active sessions and their IPs
active_sessions = {}

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
        
        # Ensure all expected choices are in the results
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
    # Convert credentials list to text format
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

@app.route('/')
def index():
    # Redirect to the registration page by default
    return redirect(url_for('register'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        is_new_student = request.form['is_new_student']
        
        # Remove spaces and hyphens from first and last names
        first_name = first_name.replace(" ", "").replace("-", "")
        last_name = last_name.replace(" ", "").replace("-", "")
        
        # Generate the email
        if is_new_student == "yes":
            email = f"{first_name.lower()}.{last_name.lower()}.23@edu.uiz.ac.ma"
        else:
            email = f"{first_name.lower()}.{last_name.lower()}@edu.uiz.ac.ma"
        
        # Check if the email already exists
        credentials = read_credentials()
        if any(credential[0] == email for credential in credentials):
            flash('This email already exists.', 'danger')
            return redirect(url_for('register'))

        # Create a hashed password
        hashed_password = sha256(email.encode()).hexdigest()[:8] # Slicing the first 8 characters of the email
        
        # Prepare the new credential
        new_credential = [email, hashed_password, '0']  # status '0' for not voted
        
        # Send email with the hashed password
        subject = "Welcome to the Voting Platform"
        body = f"Hello {first_name},\n\nYour account has been created. Here is your login information:\n\nEmail: {email}\nPassword: {hashed_password}\n\nPlease log in to cast your vote."
        send_email(subject, email, body)
        
        # Update the credentials file
        credentials.append(new_credential)
        update_credentials_file(credentials)
        
        flash('Registration successful! Please check your email for login details.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user_ip = request.remote_addr
        credentials = read_credentials()

        for credential in credentials:
            if credential[0] == email and credential[1] == password:
                if credential[2] == '0':
                    # Check if this email is already logged in from a different IP
                    if email in active_sessions and active_sessions[email]['ip'] != user_ip:
                        flash('This account is already logged in from another IP.')
                        return render_template('login.html')

                    # Set session as permanent and track IP
                    flask_session.permanent = True
                    flask_session['logged_in_email'] = email
                    active_sessions[email] = {'ip': user_ip, 'last_active': time.time()}

                    return redirect(url_for('vote', email=email))
                else:
                    flash('This account has already been used for voting. Please contact the admin in case you didn\'t.')
                    return render_template('login.html')

        flash('Invalid email or password.')
    return render_template('login.html')

@app.route('/vote/<email>', methods=['GET', 'POST'])
def vote(email):
    # Check if the user is logged in
    if 'logged_in_email' not in flask_session or flask_session['logged_in_email'] != email:
        flash('You must be logged in to vote.')
        return redirect(url_for('login'))

    # Check for session expiration
    user_ip = request.remote_addr
    if email not in active_sessions or active_sessions[email]['ip'] != user_ip:
        flask_session.pop('logged_in_email', None)
        flash('Session ended, try login again.')
        return redirect(url_for('login'))

    # Update last active time
    active_sessions[email]['last_active'] = time.time()

    if request.method == 'POST':
        choice = request.form['choice']
        results = read_results()
        results[choice] += 1

        # Update the results file on Firebase
        update_results_file(results)

        # Update the user's voting status
        credentials = read_credentials()
        for credential in credentials:
            if credential[0] == email:
                credential[2] = '1'  # Mark the user as having voted
                break

        # Update the credentials file on Firebase
        update_credentials_file(credentials)

        # Send confirmation email to the user
        subject = "Vote Confirmation"
        body = f"Hello, we received your vote. You voted for {choice}. Thank you very much!"
        send_email(subject, email, body)

        # Send notification email to yourself
        admin_subject = f"New Vote from {email}"
        admin_body = f"The email {email} voted for choice {choice}."
        send_email(admin_subject, sender, admin_body)

        # Clear the session and active sessions
        flask_session.pop('logged_in_email', None)
        active_sessions.pop(email, None)

        flash('Vote submitted successfully!')
        return redirect(url_for('login'))

    return render_template('vote.html', email=email)

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html'), 500

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        email = request.form['email']
        message = request.form['message']

        # Send email to admin
        subject = "Contact Form Submission"
        body = f"Email: {email}\nMessage: {message}"
        send_email(subject, "amineaithamma2004@gmail.com", body)

        flash('Thank you for contacting us!')
        return redirect(url_for('contact'))
    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True)
