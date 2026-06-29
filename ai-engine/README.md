# AI Engine Modules

Each subfolder will host one bounded capability of the Computer Vision pipeline.
Concrete implementations are out of scope for Sprint 01.

| Folder         | Purpose (planned)                                       |
| -------------- | ------------------------------------------------------- |
| `detection/`   | YOLOv8-based object detection                           |
| `tracking/`    | ByteTrack multi-object tracking                         |
| `recognition/` | Product / customer recognition                          |
| `cart/`        | Virtual shopping cart logic                             |
| `heatmap/`     | Spatial heatmap generation                              |
| `analytics/`   | Behavior analytics                                      |
| `inventory/`   | Shelf monitoring & stock-out detection                  |
| `models/`      | Model definitions (architecture, post-processing)       |
| `weights/`     | Trained model artifacts (gitignored)                    |
| `datasets/`    | Local datasets (gitignored)                             |
| `services/`    | Service-layer interfaces                                |
| `utils/`       | Shared helpers                                          |
