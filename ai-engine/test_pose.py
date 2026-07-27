import cv2
from ultralytics import YOLO
import sys
import os

def main():
    print("Loading models...")
    pose_path = "/models/yolov8n-pose.pt"
    if not os.path.exists(pose_path):
        pose_path = "models/yolov8n-pose.pt"
    if not os.path.exists(pose_path):
        pose_path = "yolov8n-pose.pt"
        
    det_path = "/models/yolov8n.pt"
    if not os.path.exists(det_path):
        det_path = "models/yolov8n.pt"
    if not os.path.exists(det_path):
        det_path = "yolov8n.pt"

    model_pose = YOLO(pose_path)
    model_det = YOLO(det_path)
    
    rtsp_url = "rtsp://rtsp-sim:8554/cam-a8656a93-c14f-40a8-8ad3-0a43d95ca098"
    print("Opening video stream:", rtsp_url)
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print("Error: Could not open RTSP stream.")
        return
        
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("Error: Could not read frame from RTSP stream.")
        return
        
    print(f"Read frame of shape: {frame.shape}")
    
    print("Running Pose Model...")
    pose_results = model_pose.track(
        source=frame,
        persist=True,
        tracker="bytetrack.yaml",
        classes=[0],
        verbose=False,
    )
    if pose_results:
        first = pose_results[0]
        if first.boxes is not None:
            print(f"Pose detections: {len(first.boxes)} boxes found")
            for i, box in enumerate(first.boxes):
                tid = box.id
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                xy = box.xyxy[0].tolist()
                print(f"  Box {i}: id={tid}, class={cls}, conf={conf:.2f}, xy={xy}")
                if first.keypoints is not None and first.keypoints.xy is not None:
                    kpts = first.keypoints.xy.cpu().numpy()[i]
                    print(f"    Keypoints count: {len(kpts)}")
                    if len(kpts) > 10:
                        lw = kpts[9]
                        rw = kpts[10]
                        print(f"    Left Wrist: {lw}, Right Wrist: {rw}")
        else:
            print("Pose detections: No boxes attribute in result")
    else:
        print("Pose detections: Empty result")
        
    print("Running Det Model...")
    det_results = model_det.track(
        source=frame,
        persist=True,
        tracker="bytetrack.yaml",
        verbose=False,
    )
    if det_results:
        first = det_results[0]
        if first.boxes is not None:
            print(f"Det detections: {len(first.boxes)} boxes found")
            for i, box in enumerate(first.boxes):
                tid = box.id
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                xy = box.xyxy[0].tolist()
                print(f"  Box {i}: id={tid}, class={cls} ({first.names.get(cls, str(cls))}), conf={conf:.2f}")
        else:
            print("Det detections: No boxes attribute in result")
    else:
        print("Det detections: Empty result")

if __name__ == "__main__":
    main()
