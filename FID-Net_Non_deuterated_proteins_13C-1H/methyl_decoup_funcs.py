#!/usr/bin/python

# Gogulan Karunanithy, UCL, 2023

import numpy as np
import tensorflow as tf
from tensorflow import keras
import nmrglue as ng
import json, sys,copy, os
from tensorflow.keras.mixed_precision import experimental as mixed_precision

C13_MODEL = '/home/gogs/Methyl_Large_Proteins/fidnet_13c_methyl.h5'
H1_MODEL = '/home/gogs/Methyl_Large_Proteins/fidnet_1h_methyl.h5'


def read_data(infile):
    dic, data = ng.pipe.read(infile)
    udic = ng.pipe.guess_udic(dic,data)

    return dic, data


def build_model_wavenet_large():

    def ft_layer(x):
        ft = tf.transpose(x, perm = [0,2,1,3])
        ft = tf.reshape(ft, [-1,4,512,2])
        ft = tf.complex(ft[:,:,:,0],ft[:,:,:,1])
        ft = keras.layers.Lambda(tf.signal.fft)(ft)
        ft = tf.transpose(ft, perm = [0,2,1])
        ft = tf.math.real(ft)
        ft = keras.layers.Activation('linear', dtype='float32')(ft)

        return ft

    def waveLayer(x,num_filters,dil):
        y1 = keras.layers.Conv2D(filters = num_filters, kernel_size=[8,4],
                                padding="same", dilation_rate=[dil,1])(x)

        y2 = keras.layers.Conv2D(filters = num_filters, kernel_size=[8,4],
                                    padding="same", dilation_rate=[dil,1])(x)

        y1 = keras.layers.Activation('tanh')(y1)
        y2 = keras.layers.Activation('sigmoid')(y2)

        z = y1*y2
        z =  keras.layers.Conv2D(filters = num_filters*2, kernel_size=[8,4], padding="same")(z)


        return keras.layers.Add()([z,x]), z

    num_filters = 64
    blocks = 3
    dilations = [1,2,4,6,8,10,12,14,16,20,24,28,32,40,48,56,64]
    input =  keras.layers.Input(shape=[1024, 4, 1])
    x = input
    skips = []

    for dil in dilations*blocks:
        x, skip = waveLayer(x, num_filters, dil)
        skips.append(skip)

    x = keras.layers.Activation("relu")(keras.layers.Add()(skips))
    x = keras.layers.Conv2D(num_filters, kernel_size=[8,4],padding="same", activation="relu")(x)
    fin = keras.layers.Conv2D(1, kernel_size=[8,4], padding="same", activation="tanh", dtype = 'float32')(x)
    ft_fin = ft_layer(fin)
    model = keras.Model(inputs=[input], outputs=[fin,ft_fin])
    model.compile(loss=["mse","mse"], loss_weights = [0.0,1.0],
                    optimizer=keras.optimizers.RMSprop(lr=1.0e-4))

    return model



def build_model_wavenet():


    def ft_layer(x):
        ft = tf.transpose(x, perm = [0,2,1,3])
        ft = tf.reshape(ft, [-1,4,256,2])
        ft = tf.complex(ft[:,:,:,0],ft[:,:,:,1])

        ft = keras.layers.Lambda(tf.signal.fft)(ft)
        ft = tf.transpose(ft, perm = [0,2,1])
        ft = tf.math.real(ft)
        ft = keras.layers.Activation('linear', dtype='float32')(ft)

        return ft

    def waveLayer(x,num_filters,dil):
        y1 = keras.layers.Conv2D(filters = num_filters, kernel_size=[8,4],
                                padding="same", dilation_rate=[dil,1])(x)

        y2 = keras.layers.Conv2D(filters = num_filters, kernel_size=[8,4],
                                    padding="same", dilation_rate=[dil,1])(x)

        y1 = keras.layers.Activation('tanh')(y1)
        y2 = keras.layers.Activation('sigmoid')(y2)

        z = y1*y2
        z =  keras.layers.Conv2D(filters = num_filters*2, kernel_size=[8,4], padding="same")(z)


        return keras.layers.Add()([z,x]), z

    num_filters = 64
    blocks = 3

    dilations = [1,2,4,6,8,10,12,14,16,20,24,28,32]
    input =  keras.layers.Input(shape=[512, 4, 1])
    x = input

    skips = []

    for dil in dilations*blocks:
        x, skip = waveLayer(x, num_filters, dil)
        skips.append(skip)

    x = keras.layers.Activation("relu")(keras.layers.Add()(skips))
    x = keras.layers.Conv2D(num_filters, kernel_size=[8,4],padding="same", activation="relu")(x)
    fin = keras.layers.Conv2D(1, kernel_size=[8,4], padding="same", activation="tanh", dtype = 'float32')(x)
    ft_fin = ft_layer(fin)
    model = keras.Model(inputs=[input], outputs=[fin,ft_fin])
    model.compile(loss=["mse","mse"], loss_weights = [0.0,1.0],
                    optimizer=keras.optimizers.RMSprop(lr=1.0e-4))

    return model

def do_recon_3d(infile, outfile, mode = 'dec'):
    if mode == 'dec':
        model = build_model_wavenet_large()
        model.load_weights(C13_MODEL)
        maxpoints = 1024
        dic, data = read_data(infile)
        print(data.shape)

        data = np.transpose(data, [1,2,0])
        print(data.shape)

    else:
        model = build_model_wavenet()
        model.load_weights(H1_MODEL)
        maxpoints = 512

        dic, data = read_data(infile)
        print(data.shape)

        data = np.transpose(data, [0,2,1])
        print(data.shape)

    noesy_dim = data.shape[0]
    c_dim = data.shape[2]
    h_dim = data.shape[1]

    full_max = np.max(data)
    data = data/full_max

    data_new = np.zeros_like(data)
    for i in range(noesy_dim):
        print('doing slice ', i+1, ' of ', noesy_dim, '...')
        print('slice shape = ', data[i,:,:].shape)
        samp_av, scale = setup_2d_plane(data[i,:,:], maxpoints)
        print('input shape = ', tf.shape(samp_av))
        res = model.predict(samp_av)
        res = tf.convert_to_tensor(res[0])
        res = rescale_dat(res,scale, maxpoints)
        res = get_average_results(res, h_dim, maxpoints)
        res = res[:,:c_dim,:,0]
        data_new[i,:,:] = np.transpose(res.numpy()[0,:,:])

    print('final_shape = ', data_new.shape)
    if mode == 'dec':
        data_new = np.transpose(data_new, [2,0,1])
    else:
        data_new = np.transpose(data_new, [0,2,1])
    print('final_shape = ', data_new.shape)
    ng.pipe.write(outfile,dic,data_new,overwrite=True)


def do_recon_indirect(infile, outfile, mode = 'dec'):

    if mode == 'dec':
        model = build_model_wavenet_large()
        model.load_weights(C13_MODEL)
        maxpoints = 1024
    else:
        model = build_model_wavenet()
        model.load_weights(H1_MODEL)
        maxpoints = 512
    dic,data = read_data(infile)



    print(data.shape)

    Hpoints = data.shape[1]
    Cpoints = data.shape[0]
    print('cpoints = ', Cpoints)
    dic_dl = copy.deepcopy(dic)


    if Cpoints>maxpoints:
        data = data[:maxpoints,:]
        Cpoints = maxpoints
        dic_dl['FDSLICECOUNT'] = Cpoints//2
        dic_dl['FDF1APOD'] = Cpoints//2
        dic_dl['FDF1TDSIZE'] = Cpoints//2
        dic_dl['FDSPECNUM'] = Cpoints//2

    full_max = np.max(np.fabs(data))
    data = data/full_max
    data = np.transpose(data)

    samp_av, scale = setup_2d_plane(data, maxpoints)

    res = model.predict(samp_av)

    res = tf.convert_to_tensor(res[0])
    res = rescale_dat(res,scale, maxpoints)
    res = get_average_results(res, data.shape[0], maxpoints)
    res = res[:,:Cpoints,:,0]
    data_fin = res.numpy()[0,:,:]

    data_fin = data_fin*full_max
    ng.pipe.write(outfile,dic_dl,data_fin,overwrite=True)

    data = tf.convert_to_tensor(data)
    data = tf.expand_dims(data,axis=0)
    data = tf.transpose(data, perm = [0,2,1])

    data_ft = ft_second(data, npoints1=Hpoints, npoints2=Cpoints, f1180=True, shift = False)
    data_ft = data_ft/tf.reduce_max(data_ft)

    res_ft = ft_second(res, npoints1=Hpoints, npoints2=Cpoints, f1180=True, shift = False)
    res_ft = res_ft/tf.reduce_max(res_ft)



def ft_second(ft, npoints1=128, npoints2=100, f1180 = False, shift = False, smile=False):
    if not smile:
        ft = tf.transpose(ft, perm = [0,2,1])
        ft = tf.reshape(ft, [1,npoints1,npoints2//2,2])
        ft = tf.complex(ft[...,0],ft[...,1])

    ft = np.array(ft)

    ft = ng.proc_base.sp(ft, off=0.42, end=0.98, pow=2.0, inv=False, rev=False)
    ft = ng.proc_base.zf(ft, npoints2//2)

    if not f1180:
        ft[...,0] = ft[...,0]*0.5
    ft = tf.convert_to_tensor(ft)
    if shift:
        ft = tf.signal.fftshift(tf.signal.fft(ft),axes=2)
    else:
        ft = tf.signal.fft(ft)
    if f1180:
        ft = np.array(ft)
        ft = ng.proc_base.ps(ft, p0=90.0, p1=-180.0, inv=False)
        ft = tf.convert_to_tensor(ft)

    ft = tf.transpose(ft, perm = [0,2,1])
    ft = tf.math.real(ft)

    return ft


def setup_2d_plane(ft1_samp,tot):

    ft1_samp = tf.convert_to_tensor(ft1_samp)
    padding_recon = [[3,3],[0,tot-tf.shape(ft1_samp)[1]]]
    samp_av = tf.pad(ft1_samp, padding_recon, 'Constant', constant_values = 0.0)
    scale = np.array([np.max(np.fabs(samp_av[i:i+4,:])) for i in range((tf.shape(ft1_samp)[0]+3))])

    sampy = np.zeros((scale.shape[0], 4, tf.shape(samp_av)[1]))
    for i in range(scale.shape[0]):
        sampy[i,:,:] = samp_av[i:i+4,:]

    samp_av = tf.convert_to_tensor(sampy)
    samp_av = tf.transpose(samp_av, perm = [0,2,1])
    samp_av = tf.transpose(samp_av, perm = [2,1,0])

    samp_av = samp_av/scale
    samp_av = tf.transpose(samp_av, perm = [2,1,0])
    samp_av = tf.expand_dims(samp_av,axis=3)

    return samp_av, scale

def get_average_results(dat,Hpoints,tot):
    print('in shape...,', tf.shape(dat))
    res_div = np.zeros((tot,Hpoints), dtype = np.float32)
    for i in range(Hpoints):
        ind = 4*i + 3
        res_div[:,i] = 0.25*(dat[0,:,ind,0]+dat[0,:,ind+3,0]+dat[0,:,ind+6,0]+dat[0,:,ind+9,0])

    res_div = tf.convert_to_tensor(res_div)
    res_div = tf.expand_dims(res_div,axis=0)
    res_div = tf.expand_dims(res_div,axis=3)

    return res_div


def rescale_dat(dat,scale,tot):
    dat = tf.transpose(dat, perm=[3,1,2,0])
    dat = dat*scale
    dat = tf.transpose(dat, perm=[3,1,2,0])
    dat = tf.transpose(dat, perm=[0,2,1,3])
    dat = tf.reshape(dat, [1,-1,tot,1])
    dat = tf.transpose(dat, perm=[0,2,1,3])
    return dat
