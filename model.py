# File: model.py

import torch
import torch.nn as nn
import timm

# This class MUST be identical to the one in your training script
class VisionTransformerAccidentDetector(nn.Module):
    def __init__(self, num_features, num_classes, hidden_size=256, dropout=0.5):
        super(VisionTransformerAccidentDetector, self).__init__()
        # Create the model structure WITHOUT trying to download pretrained weights
        self.base_model = timm.create_model('vit_tiny_patch16_224', pretrained=False, num_classes=0, global_pool='avg')
        num_video_features = self.base_model.num_features
        self.video_gru = nn.GRU(input_size=num_video_features, hidden_size=hidden_size, batch_first=True)
        self.feature_gru = nn.GRU(input_size=num_features, hidden_size=hidden_size // 4, batch_first=True)
        self.classifier = nn.Sequential(nn.Linear(hidden_size + hidden_size // 4, 512), nn.ReLU(), nn.Dropout(dropout), nn.Linear(512, num_classes))

    def forward(self, video_input, feature_input):
        batch_size, clip_len, C, H, W = video_input.shape
        video_input_reshaped = video_input.view(batch_size * clip_len, C, H, W)
        video_features = self.base_model(video_input_reshaped)
        video_features_seq = video_features.view(batch_size, clip_len, -1)
        _, video_hidden = self.video_gru(video_features_seq)
        _, feature_hidden = self.feature_gru(feature_input)
        video_hidden = video_hidden.squeeze(0); feature_hidden = feature_hidden.squeeze(0)
        fused = torch.cat((video_hidden, feature_hidden), dim=1)
        return self.classifier(fused)