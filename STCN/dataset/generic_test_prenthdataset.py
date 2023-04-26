import os
from os import path

import torch
from torch.utils.data.dataset import Dataset
from torchvision import transforms
from torchvision.transforms import InterpolationMode
from PIL import Image
import numpy as np

from dataset.range_transform import im_normalization
from dataset.util import all_to_onehot
import matplotlib.pyplot as plt
import glob


class GenericTestDataset(Dataset):
    def __init__(self, imagedir,maskdir,task,btype, window, res=480):
        self.image_dir = imagedir
        self.mask_dir = maskdir
        self.window = window
        self.btype = btype
        self.videos = []
        self.shape = {}
        self.frames = {}
        
        if task =='Suturing':
            vid_list = np.array(['Suturing_S02_T04','Suturing_S02_T01', 'Suturing_S03_T04','Suturing_S03_T05','Suturing_S05_T03'])
            self.prestore_mask = glob.glob(f'/Documents/video_object_segmentation/pre_stored/Suturing/Suturing_S02_T03/{self.btype}/annotation/*')[-1]
            self.prestore_img = glob.glob(f'/Documents/video_object_segmentation/pre_stored/Suturing/Suturing_S02_T03/{self.btype}/image/*')[-1]
        elif task=='Needle_Passing':
            vid_list = np.array(['Needle_Passing_S04_T01','Needle_Passing_S05_T03','Needle_Passing_S05_T05'])   
            self.prestore_mask = glob.glob(f'/Documents/video_object_segmentation/pre_stored/Needle_Passing/Needle_Passing_S03_T02/{self.btype}/annotation/*')[-1]
            self.prestore_img = glob.glob(f'/Documents/video_object_segmentation/pre_stored/Needle_Passing/Needle_Passing_S03_T02/{self.btype}/image/*')[-1]
        else:
            vid_list = np.array(['Knot_Tying_S09_T05','Knot_Tying_S05_T05','Knot_Tying_S03_T05','Knot_Tying_S05_T03','Knot_Tying_S03_T02'])
            self.prestore_mask = glob.glob(f'/Documents/video_object_segmentation/pre_stored/Knot_Tying/Knot_Tying_S02_T04/{self.btype}/annotation/*')[-1]
            self.prestore_img =glob.glob(f'/Documents/video_object_segmentation/pre_stored/Knot_Tying/Knot_Tying_S02_T04/{self.btype}/image/*')[-1]

        for vid in vid_list:
            frames = sorted(os.listdir(os.path.join(self.image_dir, vid)))
            self.frames[vid] = frames

            self.videos.append(vid)
            import fnmatch
            first_mask = os.listdir(path.join(self.mask_dir, vid))#[0]
            first_mask = fnmatch.filter(first_mask, '*.png')
            first_mask = sorted(first_mask)[0]
            _mask = np.array(Image.open(path.join(self.mask_dir, vid, first_mask)).convert("P")) # change to L
            self.shape[vid] = np.shape(_mask)

        if res != -1:
            self.im_transform = transforms.Compose([
                transforms.ToTensor(),
                im_normalization,
                transforms.Resize(res, interpolation=InterpolationMode.BICUBIC),
            ])

            self.mask_transform = transforms.Compose([
                transforms.Resize(res, interpolation=InterpolationMode.NEAREST),
            ])
        else:
            self.im_transform = transforms.Compose([
                transforms.ToTensor(),
                im_normalization,
            ])

            self.mask_transform = transforms.Compose([
            ])

    def __getitem__(self, idx):
        video = self.videos[idx]
        

        vid_im_path = path.join(self.image_dir, video)
        vid_gt_path = path.join(self.mask_dir, video)

        frames = self.frames[video]
        lf = len(frames)
        datas = []
        window = self.window
        for subframe in range(0, lf , window):
            end_frame = min(subframe+window,lf)
            info = {}
            info['name'] = video
            info['frames'] = end_frame-subframe #self.frames[video] 
            info['size'] = self.shape[video] # Real sizes
            info['gt_obj'] = {} # Frames with labelled objects

            images = []
            masks = []
            counter = 0
            ii = 0  
            new_frame = []
            
            for idx in range(subframe,end_frame): 
                f = frames[idx]
                mask_file = path.join(vid_gt_path, f) # deeplab .replace('.png','_pred.png')
                if path.exists(self.prestore_mask) and counter ==0:
                    mask = Image.open(self.prestore_mask).convert('L')# convert to P * origin

                    #print(np.asarray(mask).shape)
                    
                    masks.append(np.array(mask, dtype=np.uint8))
                    
                    this_labels = np.unique(np.asarray(masks[-1]))
                    npmask = np.array(mask, dtype=np.uint8)
                    aream = np.count_nonzero(npmask.flatten()>0)
                    if len(this_labels)==1 or aream < 100:
                        masks.pop(-1)
                        #frames.remove(f)
                        continue
                    #print(f'this_labels {mask_file}' )
                    
                    
                    #masks.append(np.array(mask, dtype=np.uint8))
                    this_labels = this_labels[this_labels!=0]
                    
                    info['gt_obj'][ii] = this_labels
                    ii += 1
                    counter += 1
                    new_frame.append(f)
                    img = Image.open(self.prestore_img).convert('RGB')
                    images.append(self.im_transform(img))
                    #print('image'+path.join(vid_im_path, f))
                elif not path.exists(self.prestore_mask) and counter==0:
                    continue
                else:
                    # Mask not exists -> nothing in it
                    masks.append(np.zeros(self.shape[video]))
                    new_frame.append(f)
                    img = Image.open(path.join(vid_im_path, f)).convert('RGB')
                    images.append(self.im_transform(img))
                
                
                
                
            info['frames'] = new_frame
            if len(images)==0:continue
            images = torch.stack(images, 0)
            #print(new_frame)
            
            masks = np.stack(masks, 0)
            
            
            
            # Construct the forward and backward mapping table for labels
            # this is because YouTubeVOS's labels are sometimes not continuous
            # while we want continuous ones (for one-hot)
            # so we need to maintain a backward mapping table
            
            labels = np.unique(masks).astype(np.uint8)
            labels = labels[labels!=0]
            
            info['label_convert'] = {}
            info['label_backward'] = {}
            idx = 1
            for l in labels:
                info['label_convert'][l] = idx
                info['label_backward'][idx] = l
                idx += 1
            masks = torch.from_numpy(all_to_onehot(masks, labels)).float()

            # Resize to 480p
            masks = self.mask_transform(masks)
            masks = masks.unsqueeze(2)

            info['labels'] = labels

            data = {
                'rgb': images,
                'gt': masks,
                'info': info#,
                #'palette': np.array(palette),
            }
            datas.append(data)

        return datas

    def __len__(self):
        return len(self.videos) 