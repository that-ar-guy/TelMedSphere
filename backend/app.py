import datetime
import uuid
from flask import Flask, request, Response, redirect, render_template, send_from_directory, jsonify, url_for
import secrets
import stripe
from flask_mail import Mail, Message
from flask_bcrypt import Bcrypt
from flask_jwt_extended import create_access_token, JWTManager
from flask_cors import CORS
import pymongo
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import os
import json
from threading import Thread
import requests
from twilio.rest import Client
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, auth

load_dotenv()
secret_key = secrets.token_hex(16)

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SECRET_KEY'] = secret_key
SECRET_KEY = os.getenv('SECRET')

app.config['MAIL_SERVER']='smtp.gmail.com'
app.config['MAIL_PORT'] = os.getenv('PORT')
app.config['MAIL_USERNAME'] = os.getenv('HOST_EMAIL')
app.config['MAIL_PASSWORD'] = os.getenv('PASSWORD')
app.config['MAIL_USE_TLS'] = True
mail = Mail(app)

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
jwt = JWTManager(app)

CORS(app, supports_credentials=True)
bcrypt = Bcrypt(app)

URI = os.getenv("DBURL")

# Twilio Whatsapp notification variables
twilioWhatsappAccountSid = os.getenv("TWILIO_WHATSAPP_ACCOUNT_SID")
twilioWhatsappAuthToken = os.getenv("TWILIO_WHATSAPP_AUTH_TOKEN")
twilioWhatsappFrom = os.getenv("TWILIO_WHATSAPP_FROM")
whatsappclient = Client(twilioWhatsappAccountSid, twilioWhatsappAuthToken)

firebase_config = {
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),  
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL"),
    "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN"),
}

if firebase_config:
    try:
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
        print("Firebase initialized successfully!")
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
else:
    print("Error: Firebase credentials not found in environment variables.")

client = pymongo.MongoClient(URI, server_api=ServerApi('1'))

doctor = client.get_database("telmedsphere").doctors
patients = client.get_database("telmedsphere").patients
feedback = client.get_database("telmedsphere").feedback

YOUR_DOMAIN = os.getenv('DOMAIN') 


# Test MongoDB connection
try:
    client.admin.command('ping')
    print("MongoDB connection successful!")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
@app.get("/")
def getInfo():
    return "WelCome to 💖TelMedSphere server !!!! "

@app.before_request
def before_request():
    if request.method == 'OPTIONS':
        return Response()

def whatsapp_message(msg):
    try:
        # Extract recipient and message content from the msg dictionary
        to = msg.get('to')  
        body = msg.get('body')  

        # Prepare the message sending parameters
        message_params = {
            "from_": twilioWhatsappFrom,
            "to": to,
            "body": body
        }

        # Send the WhatsApp message
        message = whatsappclient.messages.create(**message_params)

        print(f"Message sent! SID: {message.sid}")
        return {"status": "success", "message_sid": message.sid}
    
    except Exception as e:
        print(f"Error sending message: {str(e)}")
        return {"status": "error", "message": str(e)}

# ----------- stripe payment routes -----------------

@app.route('/checkout')
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            line_items = [
                {   
                    "price": "price_1MxPc3SAmG5gMbbMjAeavhpb",
                    "quantity": 1
                }
            ],
            mode="payment",
            success_url=YOUR_DOMAIN + "success",
            cancel_url = YOUR_DOMAIN + "failed"
        )
    except Exception as e:
        return str(e)
 
    return jsonify({'url': checkout_session.url})

@app.route('/create-payment-intent', methods=['POST'])
def create_payment():
    try:
        data = json.loads(request.data)
        print(data)
        # Create a PaymentIntent with the order amount and currency
        intent = stripe.PaymentIntent.create(
            amount=data['amount'],
            currency='inr',
            payment_method_types=['card'],
        )
        return jsonify({
            'clientSecret': intent['client_secret']
        })
    except Exception as e:
        print(e)
        return jsonify(error=str(e)), 403

# ----------- Authentication routes ----------------

@app.route('/register', methods=['POST'])
def register():
    if request.is_json:
        data = request.get_json()

        # Firebase Google Register
        if 'id_token' in data:
            try:
                decoded_token = auth.verify_id_token(data['id_token'])
                email = decoded_token.get('email')
            except:
                return jsonify({'message': 'Invalid Firebase token'}), 401
        else:
            email = data.get('email')

        if not email:
            return jsonify({'message': 'Email is required'}), 400
        
        # Custom Register
        if data['registerer'] == 'patient':
            if doctor.find_one({'email': email}) or patients.find_one({'email': email}):
                return jsonify({'message': 'User already exists'}), 400
            
            if 'id_token' not in data:
                hashed_password = bcrypt.generate_password_hash(data['passwd']).decode('utf-8')
                data['passwd'] = hashed_password
            
            # Add default values if not provided
            if 'username' not in data:
                data['username'] = 'Patient-' + email.split('@')[0]  # Username based on email
            if 'email' not in data:
                data['email'] = email
            if 'age' not in data:
                data['age'] = ''  
            if 'gender' not in data:
                data['gender'] = ''  
            if 'phone' not in data:
                data['phone'] = ''  
            if 'cart' not in data:
                data['cart'] = []  
            if 'wallet' not in data:
                data['wallet'] = 0  
            if 'wallet_history' not in data:
                data['wallet_history'] = []  
            data['upcomingAppointments'] = []
            if 'specialization' in data:
                del data['specialization']

            patients.insert_one(data)

            if 'phone' in data:
                whatsapp_message({
                    "to": f"whatsapp:{data['phone']}",
                    "body": "Thank You for Signing up on TelMedSphere"
                })

            return jsonify({
                'message': 'User created successfully',
                "username": data["username"],
                "usertype": "patient",
                "gender": data["gender"],
                "phone": data["phone"],
                "email": data["email"],
                "age": data["age"],
            }), 200
        
        elif data['registerer'] == 'doctor':
            if patients.find_one({'email': email}) or doctor.find_one({'email': email}):
                return jsonify({'message': 'User already exists'}), 400

            if 'id_token' not in data:
                hashed_password = bcrypt.generate_password_hash(data['passwd']).decode('utf-8')
                data['passwd'] = hashed_password
            
           # Add default values if not provided
            if 'username' not in data:
                data['username'] = 'Doctor-' + email.split('@')[0]  # Username based on email
            if 'email' not in data:
                data['email'] = email 
            if 'specialization' not in data:
                data['specialization'] = ''  
            if 'gender' not in data:
                data['gender'] = ''  
            if 'phone' not in data:
                data['phone'] = ''  
            if 'appointments' not in data:
                data['appointments'] = 0  
            if 'stars' not in data:
                data['stars'] = 0  
            if 'status' not in data:
                data['status'] = 'offline'  
            if 'upcomingAppointments' not in data:
                data['upcomingAppointments'] = []  
            if 'fee' not in data:
                data['fee'] = 0  
            if 'verified' not in data:
                data['verified'] = False  
            if 'cart' not in data:
                data['cart'] = [] 
            if 'meet' not in data:
                data['cart'] = []  
            if 'wallet_history' not in data:
                data['wallet_history'] = []  
            if 'wallet' not in data:
                data['wallet'] = 0 

            doctor.insert_one(data)

            return jsonify({
                'message': 'User created successfully',
                "username": data["username"],
                "usertype": "doctor",
                "gender": data["gender"],
                "phone": data["phone"],
                "email": data["email"],
                "specialization": data["specialization"],
                "verified": data["verified"]
            }), 200
        
        else:
            return jsonify({'message': 'Invalid registerer type'}), 400
    else:
        return jsonify({'message': 'Invalid request'}), 400

@app.route('/login', methods=['POST'])
def login():
    if not request.is_json:
        return jsonify({"msg": "Missing JSON in request"}), 400
    data = request.get_json()

    # Firebase Google Login
    if 'id_token' in data:
        try:
            decoded_token = auth.verify_id_token(data['id_token'])
            email = decoded_token.get('email')
        except:
            return jsonify({'message': 'Invalid Firebase token'}), 401
    else:
        email = data.get('email')

    if not email:
        return jsonify({'message': 'Email is required'}), 400
    
    # Custom Login
    var = patients.find_one({'email': email})
    if var:
        if 'id_token' in data or ('passwd' in data and bcrypt.check_password_hash(var['passwd'], data['passwd'])):
            access_token = create_access_token(identity=email)
            return jsonify({
                'message': 'User logged in successfully',
                'access_token': access_token,
                "username": var["username"],
                "usertype": "patient",
                "gender": var["gender"],
                "phone": var["phone"],
                "email": var["email"],
                "age": var["age"]
            }), 200
        return jsonify({'message': 'Invalid password'}), 400

    var = doctor.find_one({'email': email})
    if var:
        if 'id_token' in data or ('passwd' in data and bcrypt.check_password_hash(var['passwd'], data['passwd'])):
            # Update doctor status only if login is successful
            doctor.update_one({'email': email}, {'$set': {'status': 'online'}})
            access_token = create_access_token(identity=email)
            return jsonify({
                'message': 'User logged in successfully',
                'access_token': access_token,
                "username": var["username"],
                "usertype": "doctor",
                "gender": var["gender"],
                "phone": var["phone"],
                "email": var["email"],
                "specialization": var["specialization"],
                "verified": var.get("verified", False)
            }), 200
        return jsonify({'message': 'Invalid password'}), 400

    return jsonify({'message': 'Invalid username or password'}), 401
        
@app.route('/verify', methods=['POST'])
def verify():
    data = request.get_json()
    email = data['email']
    
    # Find the document with the given email
    var = doctor.find_one({'email': email})
    
    if var:
        # If the document exists, check if 'verified' field exists
        if 'verified' not in var:
            # If 'verified' field doesn't exist, add it and set to True
            doctor.update_one({'email': email}, {'$set': {'verified': True}})
        else:
            # If 'verified' exists, just ensure it's set to True
            doctor.update_one({'email': email}, {'$set': {'verified': True}})
        
        verified = True  # Since we just set it to True
    else:
        verified = False  # If the document doesn't exist, treat as unverified
    
    return jsonify({'message': 'verification details', "verified": verified}), 200

@app.route('/forgot_password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    print(data)
    email = data['email']
    print(email)
    
    user = patients.find_one({'email': email}) or doctor.find_one({'email': email})
    if not user:
        return jsonify({'message': 'User not found'}), 404

    # Generate a password reset token
    token = secrets.token_urlsafe(16)

    # Store the token in the user's document with an expiration time
    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    patients.update_one({'email': email}, {'$set': {'reset_token': token, 'reset_token_expiration': expiration_time}})
    doctor.update_one({'email': email}, {'$set': {'reset_token': token, 'reset_token_expiration': expiration_time}})

    # Send the token to the user's email
    reset_url = url_for('reset_password', token=token, _external=True)
    msg = Message("Password Reset Request",
                    sender=os.getenv('HOST_EMAIL'),
                    recipients=[email])
    msg.body = f"To reset your password, visit the following link: https://pratik0112-telmedsphere.vercel.app/reset-password/{token}"
    mail.send(msg)

    return jsonify({'message': 'Password reset link sent'}), 200


@app.route('/reset_password/<token>', methods=['POST'])
def reset_password(token):
    data = request.get_json()
    new_password = data['password']
    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')

    # Find the user with the token and check if it's still valid
    user = patients.find_one({'reset_token': token, 'reset_token_expiration': {'$gt': datetime.datetime.utcnow()}}) or \
           doctor.find_one({'reset_token': token, 'reset_token_expiration': {'$gt': datetime.datetime.utcnow()}})
    
    if not user:
        return jsonify({'message': 'The reset link is invalid or has expired'}), 400

    # Update the user's password and remove the reset token
    patients.update_one({'reset_token': token}, {'$set': {'passwd': hashed_password}, '$unset': {'reset_token': "", 'reset_token_expiration': ""}})
    doctor.update_one({'reset_token': token}, {'$set': {'passwd': hashed_password}, '$unset': {'reset_token': "", 'reset_token_expiration': ""}})

    return jsonify({'message': 'Password has been reset'}), 200

        
@app.route('/doc_status', methods=['PUT'])
def doc_status():
    data = request.get_json()
    user = data['email']
    doctor.update_one({'email': user}, {'$set': {'status': 'offline'}})
    return jsonify({'message': 'Doctor status updated successfully'}), 200



# @app.route('/meet_end', methods=['PUT'])
# def meet_end():
#     data = request.get_json()
#     user = data['email']
#     doctor.update_one({'email': user}, {'$set': {'meet': False}})
#     return jsonify({'message': 'Doctor status updated successfully'}), 200

@app.route('/get_status', methods=['GET'])
def get_status():
    details = []
    count = 0
    for i in doctor.find():
        if i.get('verified', False):
            count += 1
            details.append({"email": i["email"], "status": i.get("status", "offline"), "username": i["username"], "specialization": i["specialization"], "gender": i["gender"], "phone": i["phone"], "isInMeet": i["meet"], "noOfAppointments": i["appointments"], "noOfStars": i["stars"], "id": count, 'fee': i.get('fee', 199)})
    # print(details)
    return jsonify({"details": details}), 200

def send_message_async(msg):
    with app.app_context():
        mail.send(msg)
        # os.remove(os.path.join(app.root_path, 'upload', 'Receipt.pdf'))

@app.get('/media/<path:path>')
def send_media(path):
    return send_from_directory(
        directory='upload', path=path
    )

@app.route('/mail_file', methods=['POST'])
def mail_file():
    # Get form data
    user = request.form.get("email")
    f = request.files['file']
    
    # Save the uploaded file
    file_path = os.path.join(app.root_path, 'upload', 'Receipt.pdf')
    f.save(file_path)
    
    # Prepare the email message
    msg = Message(
        "Receipt cum Prescription for your Consultancy",
        sender="deexithmadas277@gmail.com",
        recipients=[user]
    )
    
    # Retrieve patient details from the database
    pat = patients.find_one({'email': user})
    
    # Render the email HTML template with patient's username
    msg.html = render_template('email.html', Name=pat['username'])
    
    # Prepare and send the WhatsApp message with the PDF link
    whatsapp_message({
        "to": f"whatsapp:{pat['phone']}",
        "body": "Thank you for taking our consultancy. Please find your receipt attached. [link: https://pratik0112-telmedsphere.vercel.app/]",
    })
    
    # Attach the receipt PDF to the email message
    with app.open_resource(file_path) as fp:
        msg.attach("Receipt.pdf", "application/pdf", fp.read())
    thread = Thread(target=send_message_async, args=(msg,))
    thread.start()
    
    return jsonify({"message": "Success"}), 200

# ----------- appointment routes -----------------

@app.route('/doctor_app', methods=['POST'])
def doctor_app():
    data = request.get_json()
    email = data['email']
    doctor.update_one({'email': email}, {'$inc': {'appointments': 1, 'stars': data['stars']}})
    return jsonify({'message': 'Doctor status updated successfully'}), 200

@app.route('/set_appointment', methods=['POST', 'PUT'])
def set_appointment():
    data = request.get_json()
    email = data['email']
    doc = doctor.find_one({'email': email})
    if request.method == 'POST':
        return jsonify({'message': 'Doctor Appointments', 'appointments': doc['upcomingAppointments']}), 200
    else:
        doc['upcomingAppointments'].append({
            "date": data['date'],
            "time": data['time'],
            "patient": data['patient'],
            "pemail": data['pemail'],
            "link": data['link'],
        })

        pat = patients.find_one({'email': data['pemail']})
    
        whatsapp_message({
            "to": f"whatsapp:{pat['phone']}",
            "body": "Your Appointment has been booked on " + data['date'] + " at "+ data['time'] + " with Dr. " + doc['username'] +"."
        })

        doctor.update_one({'email': email}, {'$set': {'upcomingAppointments': doc['upcomingAppointments']}})
        return jsonify({'message': 'Doctor status updated successfully'}), 200

@app.route('/patient_apo', methods=['POST', 'PUT'])
def patient_apo():
    data = request.get_json()
    email = data['email']
    pat = patients.find_one({'email': email})

    if request.method == 'POST':
        return jsonify({'message': 'Patient Appointments', 'appointments': pat['upcomingAppointments']}), 200
    else:
        pat['upcomingAppointments'].append({
            "date": data['date'],
            "time": data['time'],
            "doctor": data['doctor'],
            "demail": data['demail'],
            "link": data['link'],
        })
        patients.update_one({'email': email}, {'$set': {'upcomingAppointments': pat['upcomingAppointments']}})
        return jsonify({'message': 'Patient status updated successfully'}), 200
    
# ----------- meeting routes -----------------

@app.route('/make_meet', methods=['POST', 'PUT'])
def make_meet():
    data = request.get_json()
    email = data['email']
    if request.method == 'PUT':
        print(data['link'])
        doctor.update_one({'email': email}, {'$set': {'link': {'link': data['link'], "name": data['patient']}}})
        return jsonify({'message': 'Meet link created successfully'}), 200
    else:
        doc = doctor.find_one({'email': email})
        return jsonify({'message': 'Meet link', 'link': doc.get('link', None)}), 200
    
@app.route('/meet_status', methods=['POST'])
def meet_status():
    data = request.get_json()
    user = data['email']
    details = doctor.find_one({'email': user})
    if details['meet'] == True:
        return jsonify({'message': 'Doctor is already in a meet', 'link': details.get('link', '')}), 208
    else:
        if data.get('link', '') == '':
            doctor.update_one({'email': user}, {'$set': {'meet': True}})
        else:
            doctor.update_one({'email': user}, {'$set': {'meet': True, 'link': data['link']}})
        return jsonify({'message': 'Doctor status updated successfully'}), 200

@app.route('/delete_meet', methods=['PUT'])
def delete_meet():
    data = request.get_json()
    email = data['email']
    doctor.update_one({'email': email}, {'$unset': {'link': None, 'currentlyInMeet': None}})
    doctor.update_one({'email': email}, {'$set': {'meet': False}})

    return jsonify({'message': 'Meet link deleted successfully'}), 200

@app.route('/currently_in_meet', methods=['POST', 'PUT'])
def currently_in_meet():
    data = request.get_json()
    email = data['email']
    if request.method == 'PUT':
        doctor.update_one({'email': email}, {'$set': {'currentlyInMeet': True}})
        return jsonify({'message': 'Currently in meet'}), 200
    else:
        doc = doctor.find_one({'email': email})
        return jsonify({'message': 'Currently in meet', 'curmeet': doc.get('currentlyInMeet', False)}), 200
    
# @app.route('/delete_currently_in_meet', methods=['PUT'])
# def delete_currently_in_meet():
#     data = request.get_json()
#     email = data['email']
#     return jsonify({'message': 'Not Currently in meet'}), 200
    
@app.route("/doctor_avilability", methods=['PUT'])
def doctor_avilability():
    data = request.get_json()
    user = data['email']
    doctor.update_one({'email': user}, {'$set': {'status': 'online'}})
    return jsonify({'message': 'Doctor status updated successfully'}), 200

# ----------- orders routes -----------------
@app.route("/add_order", methods=['POST'])
def add_order():
    data = request.get_json()
    email = data['email']
    print(data)
    var = patients.find_one({'email': email})
    if var:
        orders = var.get('orders', [])
        for i in data["orders"]:
            i['key'] = str(uuid.uuid4())
            i['Ordered_on'] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            orders.append(i)
        patients.update_one({'email': email}, {'$set': {'orders': orders}})
        return jsonify({'message': 'Order added successfully'}), 200
    else:
        var = doctor.find_one({"email":email})
        orders = var.get('orders', [])
        for i in data["orders"]:
            i['key'] = str(uuid.uuid4())
            i['Ordered_on'] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            orders.append(i)
        doctor.update_one({'email': email}, {'$set': {'orders': orders}})
        return jsonify({'message': 'Order added successfully'}), 200
    
@app.route("/get_orders", methods=['POST'])
def get_orders():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email':email})
    if var:
        return jsonify({'message': 'Orders', 'orders': var['orders']}), 200
    else:
        var = doctor.find_one({'email': email})
        return jsonify({'message': 'Orders', 'orders': var['orders']}), 200

@app.route('/update_details', methods=['PUT'])
def update_details():
    data = request.get_json()
    usertype = data['usertype']
    email = data['email']
    if usertype == 'doctor':
        if data['passwd'] == '':
            doctor.update_one({'email': email}, {'$set': {'username': data['username'], 'phone': data['phone'], 'specialization': data['specialization'], 'gender': data['gender'], 'fee': data['fee']}})
        else:
            hashed_password = bcrypt.generate_password_hash(data['passwd']).decode('utf-8')
            data['passwd'] = hashed_password
            doctor.update_one({'email': email}, {'$set': {'username': data['username'], 'phone': data['phone'], 'specialization': data['specialization'], 'passwd': data['passwd'], 'gender': data['gender'], 'fee': data['fee']}})
        return jsonify({'message': 'Doctor details updated successfully'}), 200
    else:
        if data['passwd'] == '':
            patients.update_one({'email': email}, {'$set': {'username': data['username'], 'phone': data['phone'], 'age': data['age'], 'gender': data['gender']}})
        else:
            hashed_password = bcrypt.generate_password_hash(data['passwd']).decode('utf-8')
            data['passwd'] = hashed_password
            patients.update_one({'email': email}, {'$set': {'username': data['username'], 'phone': data['phone'],  'passwd': data['passwd'], 'age': data['age'], 'gender': data['gender']}})
        return jsonify({'message': 'Patient details updated successfully'}), 200

# ----------- cart routes -----------------

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        cart = var.get('cart', [])
        for i in data["cart"]:
            for j in cart:
                if j['id'] == i['id']:
                    j['quantity'] = i['quantity']
                    break
            else:
                i['key'] = str(uuid.uuid4())
                cart.append(i)
        patients.update_one({'email': email}, {'$set': {'cart': cart}})
        return jsonify({'message': 'Cart added successfully', 'cart': cart}), 200
    else:
        var = doctor.find_one({"email":email})
        cart = var.get('cart', [])
        for i in data["cart"]:
            for j in cart:
                if j['id'] == i['id']:
                    j['quantity'] = i['quantity']
                    break
            else:
                i['key'] = str(uuid.uuid4())
                cart.append(i)
        doctor.update_one({'email': email}, {'$set': {'cart': cart}})
        return jsonify({'message': 'Cart added successfully', 'cart': cart}), 200
    
@app.route("/get_cart", methods=['POST'])
def get_cart():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email':email})
    if var:
        return jsonify({'message': 'Cart', 'cart': var.get('cart', [])}), 200
    else:
        var = doctor.find_one({'email': email})
        return jsonify({'message': 'Cart', 'cart': var.get('cart', [])}), 200

@app.route('/increase_quantity', methods=['POST'])
def increase_quantity():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        for i in var['cart']:
            if i['id'] == data['id']:
                i['quantity'] += 1
                break
        patients.update_one({'email': email}, {'$set': {'cart': var['cart']}})
        return jsonify({'message': 'Quantity increased successfully'}), 200
    else:
        var = doctor.find_one({'email': email})
        for i in var['cart']:
            if i['id'] == data['id']:
                i['quantity'] += 1
                break
        doctor.update_one({'email': email}, {'$set': {'cart': var['cart']}})
        return jsonify({'message': 'Quantity increased successfully'}), 200
    
@app.route('/decrease_quantity', methods=['POST'])
def decrease_quantity():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        for i in var['cart']:
            if i['id'] == data['id']:
                i['quantity'] -= 1
                break
        patients.update_one({'email': email}, {'$set': {'cart': var['cart']}})
        return jsonify({'message': 'Quantity increased successfully'}), 200
    else:
        var = doctor.find_one({'email': email})
        for i in var['cart']:
            if i['id'] == data['id']:
                i['quantity'] -= 1
                break
        doctor.update_one({'email': email}, {'$set': {'cart': var['cart']}})
        return jsonify({'message': 'Quantity increased successfully'}), 200
    
@app.route("/delete_cart", methods=['POST'])
def delete_cart():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email':email})
    if var:
        cart = var['cart']
        for i in var['cart']:
            if i['id'] == data['id']:
                cart.remove(i)
        patients.update_one({'email': email}, {'$set': {'cart': cart}})
        return jsonify({'message': 'Cart deleted successfully'}), 200
    else:
        var = doctor.find_one({'email': email})
        cart = var['cart']
        for i in var['cart']:
            if i['id'] == data['id']:
                cart.remove(i)
        doctor.update_one({'email': email}, {'$set': {'cart': cart}})
        return jsonify({'message': 'Cart deleted successfully'}), 200
    
@app.route("/delete_all_cart", methods=['POST'])
def delete_all_cart():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({"email": email})
    if var:
        patients.update_one({'email': email}, {'$set': {'cart': []}})
        return jsonify({'message': 'Cart deleted successfully'}), 200
    else:
        doctor.update_one({'email': email}, {'$set': {'cart': []}})
        return jsonify({'message': 'Cart deleted successfully'}), 200


# ----------- wallet routes -----------------

@app.route('/wallet', methods=['POST'])
def wallet():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        wallet = var.get('wallet', 0)+round(float(data['walletAmount']))
        patients.update_one({'email': email}, {'$set': {'wallet': wallet}})
        return jsonify({'message': 'Wallet updated successfully'}), 200
    else:
        var = doctor.find_one({'email': email})
        wallet = var.get('wallet', 0)+round(float(data['walletAmount']))
        doctor.update_one({'email': email}, {'$set': {'wallet': wallet}})
        return jsonify({'message': 'Wallet updated successfully'}), 200

@app.route('/get_wallet', methods=['POST'])
def get_wallet():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        return jsonify({'message': 'Wallet', 'wallet': var.get('wallet', 0)}), 200
    else:
        var = doctor.find_one({'email': email})
        return jsonify({'message': 'Wallet', 'wallet': var.get('wallet', 0)}), 200

@app.route("/debit_wallet", methods=['POST'])
def debit_wallet():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if data.get('demail', False):
        demail = data['demail']
        doc = doctor.find_one({'email': demail})
        wallet = var.get('wallet', 0)-round(float(doc.get('fee', 0)))
        patients.update_one({'email': email}, {'$set': {'wallet': wallet}})
        return jsonify({'message': 'Wallet updated successfully'}), 200
    else:
        if var:
            wallet = var.get('wallet', 0)-round(float(data['walletAmount']))
            patients.update_one({'email': email}, {'$set': {'wallet': wallet}})
            return jsonify({'message': 'Wallet updated successfully'}), 200
        else:
            var = doctor.find_one({'email': email})
            wallet = var.get('wallet', 0)-round(float(data['walletAmount']))
            doctor.update_one({'email': email}, {'$set': {'wallet': wallet}})
            return jsonify({'message': 'Wallet updated successfully'}), 200
    
@app.route('/add_wallet_history', methods=['POST'])
def add_wallet_history():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        history = var.get('wallet_history', [])
        history.append(data['history'])
        patients.update_one({'email': email}, {'$set': {'wallet_history': history}})
        return jsonify({'message': 'Wallet history added successfully'}), 200
    else:
        var = doctor.find_one({'email': email})
        history = var.get('wallet_history', [])
        history.append(data['history'])
        doctor.update_one({'email': email}, {'$set': {'wallet_history': history}})
        return jsonify({'message': 'Wallet history added successfully'}), 200
    
@app.route('/get_wallet_history', methods=['POST'])
def get_wallet_history():
    data = request.get_json()
    email = data['email']
    var = patients.find_one({'email': email})
    if var:
        return jsonify({'message': 'Wallet history', 'wallet_history': var.get('wallet_history', [])}), 200
    else:
        var = doctor.find_one({'email': email})
        return jsonify({'message': 'Wallet history', 'wallet_history': var.get('wallet_history', [])}), 200

#------------ feedback route ------------------------------
@app.route('/feedback', methods=['POST'])
def save_feedback():
    data = request.get_json()
    try:
        # Saving feedback information
        feedback.insert_one(data);
        return jsonify({"message": "Feedback Saved Successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500     
        
@app.route('/feedback',methods=['GET'])
def get_all_feedback():
    try:
        feedbacks = list(feedback.find({}, {"_id": 0}))
        return jsonify(feedbacks),200
    except Exception as e:
        return jsonify({"error": str(e)}), 500    

@app.route('/feedback/<id>', methods=['GET'])
def get_feedback(id):
    try:
        print(f"Feedback ID: {id}")
        result = feedback.find_one({'feedbackid': str(id)})  

        print(f"Feedback: {result}")
        if result:
            # Convert ObjectId to string
            result['_id'] = str(result['_id'])
            return jsonify({"message": "Feedback found", "data": result}), 200
        else:
            return jsonify({"message": "Feedback Not Found"}), 400    

    except Exception as e:
        return jsonify({"error": str(e)}), 500
                       
# ----------- email for contact us routes -----------------
@app.route('/contact', methods=['POST'])
def contact():
    data = request.json
    try:
        # Send email notification
        msg = Message(
            subject=f"New Contact Form Submission: {data['subject']}",
            sender=data['email'],
            recipients=["telmedsphere489@gmail.com"],
            body=f"""
            New contact form submission from:
            Name: {data['name']}
            Email: {data['email']}
            Subject: {data['subject']}
            Message: {data['message']}
            """
        )
        mail.send(msg)
        return jsonify({"message": "Message sent successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
