const express = require('express');
const axios = require('axios');
const path = require('path');
const winston = require('winston');

const app = express();
const BACKEND1_URL = process.env.BACKEND1_URL || 'http://backend1:3001';

const logger = winston.createLogger({
    level: 'info',
    format: winston.format.combine(
        winston.format.timestamp(),
        winston.format.json()
    ),
    transports: [new winston.transports.Console()]
});

app.get('/', (req, res) => {
    logger.info('Serving index.html');
    res.sendFile(path.join(__dirname, 'index.html'));
});

app.get('/api/trigger', async (req, res) => {
    logger.info('Frontend triggered, sending request to Backend 1');
    try {
        const response = await axios.get(`${BACKEND1_URL}/api/process`);
        logger.info('Successfully received response from Backend 1');
        res.json({ source: 'frontend', data: response.data });
    } catch (error) {
        logger.error(`Error communicating with Backend 1: ${error.message}`, { 
            responseDetails: error.response?.data 
        });
        res.status(500).json({ error: error.message, details: error.response?.data });
    }
});

app.listen(3000, () => logger.info('Frontend listening on port 3000'));