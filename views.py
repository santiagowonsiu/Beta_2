from flask import Blueprint, render_template, request, jsonify, redirect, url_for, Response, send_file, current_app
import random
import numpy as np
import cv2
import mediapipe as mp
import pickle
import pandas as pd
from socketio_instance import socketio
from flask_socketio import SocketIO, emit
from PIL import Image
import numpy as np
import json
import zipfile
import warnings
import os
import random
import glob
import subprocess
import time
import cut_master.experiments.__main__
# This will import the __main__.py file from the cut_master package / folder to be able to access the function from the CUT model for image generation

warnings.filterwarnings('ignore')

##
#. SETUP THE BLUEPRINT AND HOME REDIRECTION
#

views = Blueprint(__name__, "views")
@socketio.on('connect')
def test_connect():
    emit('after connect',  {'data':'Lets dance'})

@views.route('/') # return html
def home():
    return render_template('index.html', name = "Santiago", age= 20)

#### POSE CLASSIFICATION MODEL USING MEDIAPIPE AND FROM THE TRAINED DATA ON FILE body_language.pkl
mp_drawing = mp.solutions.drawing_utils
mp_holistic = mp.solutions.holistic

with open('body_language.pkl', 'rb') as f:
    model = pickle.load(f)

video_feed_active = True
camera = None

@views.route('/video_feed') # return html
def video_feed():
    global video_feed_active
    video_feed_active = True
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame') # return the response object


def gen_frames(): 
    global video_feed_active
    global camera
    camera = cv2.VideoCapture(0)  # Use 0 for web camera
    previous_class = None

    with mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5) as holistic:
        while True:
            if not video_feed_active:
                # Create a black image
                image = np.zeros((480, 640, 3), dtype="uint8")
                # Put the text
                cv2.putText(image, "Paused Video", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode('.jpg', image)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')  # concat frame one by one and show result
                time.sleep(1)
            else:
                if camera is None or not camera.isOpened():
                    camera = cv2.VideoCapture(0)
                success, frame = camera.read()  # Read the camera frame
                if not success:
                    break
                else:
                    # Recolor Feed
                    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image.flags.writeable = False        

                    # Make Detections
                    results = holistic.process(image)

                    # Recolor image back to BGR for rendering
                    image.flags.writeable = True   
                    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

                    # Draw face landmarks
                    mp_drawing.draw_landmarks(image, results.face_landmarks, mp_holistic.FACEMESH_TESSELATION, 
                                            mp_drawing.DrawingSpec(color=(80,110,10), thickness=1, circle_radius=1),
                                            mp_drawing.DrawingSpec(color=(80,256,121), thickness=1, circle_radius=1)
                                            )

                    # Right hand
                    mp_drawing.draw_landmarks(image, results.right_hand_landmarks, mp_holistic.HAND_CONNECTIONS, 
                                            mp_drawing.DrawingSpec(color=(80,22,10), thickness=2, circle_radius=4),
                                            mp_drawing.DrawingSpec(color=(80,44,121), thickness=2, circle_radius=2)
                                            )

                    # Left Hand
                    mp_drawing.draw_landmarks(image, results.left_hand_landmarks, mp_holistic.HAND_CONNECTIONS, 
                                            mp_drawing.DrawingSpec(color=(121,22,76), thickness=2, circle_radius=4),
                                            mp_drawing.DrawingSpec(color=(121,44,250), thickness=2, circle_radius=2)
                                            )

                    # Pose Detections
                    mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_holistic.POSE_CONNECTIONS, 
                                            mp_drawing.DrawingSpec(color=(245,117,66), thickness=2, circle_radius=4),
                                            mp_drawing.DrawingSpec(color=(245,66,230), thickness=2, circle_radius=2)
                                            )

                    # Export coordinates
                    try:
                        # Extract Pose landmarks
                        pose = results.pose_landmarks.landmark
                        pose_row = list(np.array([[landmark.x, landmark.y, landmark.z, landmark.visibility] for landmark in pose]).flatten())
                        
                        # Extract Face landmarks
                        face = results.face_landmarks.landmark
                        face_row = list(np.array([[landmark.x, landmark.y, landmark.z, landmark.visibility] for landmark in face]).flatten())
                        
                        # Concate rows
                        row = pose_row+face_row

                        # Make Detections
                        X = pd.DataFrame([row])
                        body_language_class = model.predict(X)[0]
                        body_language_prob = model.predict_proba(X)[0]

                        #new code for socket
                        # print(f"Emitting pose classification: {body_language_class}")  # Add this line
                        socketio.emit('pose_classification', {'classification': body_language_class})
                        
                        # Grab ear coords
                        coords = tuple(np.multiply(
                                        np.array(
                                            (results.pose_landmarks.landmark[mp_holistic.PoseLandmark.LEFT_EAR].x, 
                                            results.pose_landmarks.landmark[mp_holistic.PoseLandmark.LEFT_EAR].y))
                                , [640,480]).astype(int)) #640-480 are the dimensions of the camera
                        
                        cv2.rectangle(image, 
                                    (coords[0], coords[1]+5), 
                                    (coords[0]+len(body_language_class)*20, coords[1]-30), 
                                    (245, 117, 16), -1)
                        cv2.putText(image, body_language_class, coords, 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                        
                        # Get status box
                        cv2.rectangle(image, (0,0), (250, 60), (245, 117, 16), -1)
                        
                        # Display Class
                        cv2.putText(image, 'CLASS'
                                    , (95,12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                        cv2.putText(image, body_language_class.split(' ')[0]
                                    , (90,40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                        
                        # Display Probability
                        cv2.putText(image, 'PROB'
                                    , (15,12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                        cv2.putText(image, str(round(body_language_prob[np.argmax(body_language_prob)],2))
                                    , (10,40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                        
                    except:
                        pass

                    ret, buffer = cv2.imencode('.jpg', image)
                    frame = buffer.tobytes()
                    yield (b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')  # concat frame one by one and show result

    camera.release()

## STOP THE VIDEO FEED
    
@views.route('/stop_video_feed') # return html
def stop_video_feed():
    global video_feed_active
    global camera
    video_feed_active = False
    if camera is not None:
        camera.release()
    return redirect(url_for('views.home')) 

#### 3D OBJECTS GENERATION

@views.route('/objects3d', methods=["GET"])
def generate_objects(num_objects=1):
    objects = []
    colors = [  # RGB values for the colors
        [0, 255, 0],  # Green
        [0, 0, 255],  # Blue
        [165, 42, 42],  # Brown
        [255, 165, 0]  # Orange
    ]
    for _ in range(num_objects):
        shape = np.random.choice(["sphere", "cube"])
        size = np.random.uniform(0.1, 1.0)
        x = np.random.uniform(-1.0, 1.0)
        y = np.random.uniform(-1.0, 1.0)
        z = np.random.uniform(-1.0, 1.0)
        color = colors[np.random.randint(len(colors))]  # Select a random color
        rotation = np.random.rand(3) * 0.05  # Add rotation speed
        obj = {
            "shape": shape,
            "size": size,
            "x": x,
            "y": y,
            "z": z,
            "color": color,
            "rotation": rotation.tolist()  # Add rotation speed to the object
        }
        objects.append(obj)
    return jsonify(objects)


#### EXECUTE TEST.PY AND WAIT TO RENDER THE GENERATED IMAGES

@views.route('/run_test', methods=['POST'])
def run_test_route():

    ######## Get the TestA file

    # Look for the latest downloaded image in my files
    # Link where your downloads folder is where images are automatically downloaded from a browser, it must be that folder for the model to get the image
    dir_path = '/Users/santiagowon/Downloads/'
    files = glob.glob(os.path.join(dir_path, '*.png'))
    latest_file = max(files, key=os.path.getctime)

    # Specify the target directory and file name 
    target_dir = '/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/cut_master/datasets/afhq/cat2dog/TestA'
    target_file = 'testA.png'

    # Construct the full path of the target file
    target_path = os.path.join(target_dir, target_file)

    # Copy the latest file to the target directory with the specified name
    with open(latest_file, 'rb') as fsrc:
        with open(target_path, 'wb') as fdst:
            fdst.write(fsrc.read())   

    ######## Get the TestB file: Copy Paste in TestB a random Landscape Image as input

    #Link where the dataset of lanscapes is
    source_dir = '/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/cut_master/datasets/grumpifycat/Dataset - Landscapes/All_Images'
    
    #Link where the TestB (1 landscape image) will be pasted for the model to take as reference to transform
    target_dir = '/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/cut_master/datasets/afhq/cat2dog/TestB'
    target_file = 'testB.png'

    # Get a list of all files in the source directory
    files = os.listdir(source_dir)

    # Select a random file
    random_file = random.choice(files)

    # Construct the full file paths
    source_file = os.path.join(source_dir, random_file)
    target_file = os.path.join(target_dir, target_file)

    # Copy the file
    with open(source_file, 'rb') as fsrc:
        with open(target_file, 'wb') as fdst:
            fdst.write(fsrc.read())

    # Run the script
    # Link where test.py file is
    result = subprocess.run(['/Users/santiagowon/anaconda3/bin/python', '/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/cut_master/test.py'], capture_output=True, text=True)

    # Check if the script executed successfully
    if result.returncode == 0:
        # Get the latest generated PNG file
        # Link where the model will store 3 images: The Input TestA, the Input TestB and the Output
        list_of_files = glob.glob('/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/gen_image_png')  # path for image storing
        latest_file = max(list_of_files, key=os.path.getctime)
        return send_file(latest_file, mimetype='image/png')
    else:
        return "Script execution failed", 500
    

@views.route('/latest_Fake1')
def latest_image_route1():
    # Get the latest generated PNG file
    # Make sure there is a folder created to store a duplicate of the Output images for display in the website
    list_of_files = glob.glob('/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/gen_image_display/*')  # path for image display reading
    latest_file = max(list_of_files, key=os.path.getctime)
    return send_file(latest_file, mimetype='image/png')


@views.route('/latest_Capture')
def latest_image_route2():
    # Get the latest generated PNG file
    # Make sure there is a folder created to store a duplicate of the TestA capture images for display in the website
    list_of_files = glob.glob('/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/capture_image/*')  # path for image display reading
    latest_file = max(list_of_files, key=os.path.getctime)
    return send_file(latest_file, mimetype='image/png')

@views.route('/latest_Landscape')
def latest_image_route3():
    # Get the latest generated PNG file
    # Make sure there is a folder created to store a duplicate of the TestB Lanscape Dataset image for display in the website
    list_of_files = glob.glob('/Users/santiagowon/Dropbox/Santiago/01. Maestria/AI & ML/Final Project/Learning Pieces - For Project/7. Web + GAN/landscape_image/*')  # path for image display reading
    latest_file = max(list_of_files, key=os.path.getctime)
    return send_file(latest_file, mimetype='image/png')

