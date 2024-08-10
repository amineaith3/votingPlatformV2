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
import time
from hashlib import sha256

load_dotenv()

sender = os.getenv('sender')
password = os.getenv('password')
password_admin = os.getenv('password-admin')
app = Flask(__name__)
app.secret_key = 'your_secret_key'
CREDENTIALS_URL = os.getenv('CREDENTIALS_URL')
RESULTS_URL = os.getenv('RESULTS_URL')
ENSA_STUDENTS_URL = os.getenv('ENSA_STUDENTS_URL')  # Changed variable name for clarity
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

def checktime():
    return True
    # Define the start and end date and time
    start_time = datetime(2024, 8, 10, 21, 0, 0, tzinfo=pytz.timezone('Europe/Paris'))  # 10 August 2024, 8 PM GMT+1
    end_time = datetime(2024, 8, 12, 0, 0, 0, tzinfo=pytz.timezone('Europe/Paris'))    # 12 August 2024, 12 AM GMT+1

    # Get the current time in GMT+1
    current_time = datetime.now(pytz.timezone('Europe/Paris'))

    # Check if current time is within the specified range
    return start_time <= current_time < end_time
 
@app.route('/')
def index():
    if checktime():
        # Redirect to the registration page if the current time is after or equal to the target time
        return redirect(url_for('register'))
    else:
        # Render the countdown page if the current time is before the target time
        return render_template('countdown.html')

# Function to load ENSA_STUDENTS data
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
    # Normalize the first name and last name by converting to lowercase and removing spaces and hyphens
    normalized_first_name = first_name.strip().lower().replace(" ", "").replace("-", "")
    normalized_last_name = last_name.strip().lower().replace(" ", "").replace("-", "")

    # Check if the student exists in the data
    for student in students_data:
        if student and len(student) >= 2:  # Check if there are at least two columns
            if student[0].strip().lower().replace(" ", "").replace("-", "") == normalized_first_name and \
               student[1].strip().lower().replace(" ", "").replace("-", "") == normalized_last_name:
                return True
    return False


@app.route('/register', methods=['GET', 'POST'])
def register():
    if checktime():
        students_data = load_students_data()  # Load the ENSA_STUDENTS data

        if request.method == 'POST':
            first_name = request.form['first_name'].lower()
            last_name = request.form['last_name'].lower()
            is_new_student = request.form['is_new_student']
                        
            # Check if the student exists in the ENSA_STUDENTS file
            if not check_student_exists(first_name, last_name, students_data):
                flash('You entered your data wrong, or you aren\'t an ENSA student. Please contact the admins through the contact us page.', 'danger')
                return redirect(url_for('register'))
                
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
            hashed_password = sha256(email.encode()).hexdigest()[:8]  # Slicing the first 8 characters of the email
            
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
    else:
        return render_template('countdown.html')

@app.route('/admin', methods=['GET'])
def admin():
    # Check if the user is logged in as admin
    if 'logged_in_email' not in flask_session or flask_session['logged_in_email'] != sender:
        flash('Access denied. Admins only.')
        return redirect(url_for('login'))

    # Fetch results to display
    results = read_results()

    return render_template('admin.html', results=results)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if checktime():
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
    else:
        return render_template('countdown.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        class_name = request.form['class']
        subject = request.form['subject']
        message = request.form['message']

        # Format the email body
        email_body = f"The student {first_name} {last_name}, from {class_name}, is contacting:\n{message}"

        # Handle sending the email here, using the subject
        send_email(subject, sender, email_body)

        flash('Your message has been sent!', 'success')
        return redirect(url_for('contact'))
    
    return render_template('contact.html')




@app.route('/vote/<email>', methods=['GET', 'POST'])
def vote(email):
    if checktime():
        if 'logged_in_email' not in flask_session or flask_session['logged_in_email'] != email:
            return redirect(url_for('login'))

        if request.method == 'POST':
            choice = request.form['choice']
            results = read_results()

            if choice in results:
                results[choice] += 1
                update_results_file(results)

                # Update user's status to 1 (voted)
                credentials = read_credentials()
                for i in range(len(credentials)):
                    if credentials[i][0] == email:
                        credentials[i][2] = '1'
                        break
                update_credentials_file(credentials)

                flash('Thank you for voting!')
                return redirect(url_for('logout'))

        return render_template('vote.html')
    else:
        return render_template('countdown.html')

@app.route('/logout')
def logout():
    # Remove user from session and active sessions
    email = flask_session.get('logged_in_email')
    if email:
        flask_session.pop('logged_in_email', None)
        if email in active_sessions:
            del active_sessions[email]
    
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
