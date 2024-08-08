from flask import Flask, render_template, request, redirect, url_for, flash
import os
import json
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, storage

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

def read_credentials():
    response = requests.get(CREDENTIALS_URL)
    if response.status_code == 200:
        return [line.strip().split(',') for line in response.text.splitlines()]
    else:
        return []

def read_results():
    response = requests.get(RESULTS_URL)
    if response.status_code == 200:
        return {line.split(',')[0]: int(line.split(',')[1]) for line in response.text.splitlines()}
    else:
        return {}

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

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        credentials = read_credentials()

        for credential in credentials:
            if credential[0] == email and credential[1] == password:
                if credential[2] == '0':
                    return redirect(url_for('vote', email=email))
                else:
                    flash('This account has already been used for voting. Please contact the admin in case you didn\'t')
                    return render_template('login.html')

        flash('Invalid email or password.')
    return render_template('login.html')



@app.route('/vote/<email>', methods=['GET', 'POST'])
def vote(email):
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
        send_email(admin_subject, sender, admin_body)  # Change 'sender' to your admin email if necessary

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
