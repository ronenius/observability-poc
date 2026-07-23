const express = require('express');
const axios = require('axios');
const winston = require('winston');

const app = express();
const BACKEND2_URL = process.env.BACKEND2_URL || 'http://backend2:8080';

const logger = winston.createLogger({
    level: 'info',
    format: winston.format.combine(
        winston.format.timestamp(),
        winston.format.json()
    ),
    transports: [new winston.transports.Console()]
});

app.get('/api/process', async (req, res) => {
    logger.info('Received request from frontend');

    // 10% failure probability
    if (Math.random() < 0.10) {
        logger.error('Simulated 10% failure triggered');
        return res.status(500).json({ error: 'Backend 1 failed randomly' });
    }

    try {
        const response = await axios.get(`${BACKEND2_URL}/api/data`);
        logger.info('Successfully fetched data from Backend 2');
        res.json({ source: 'backend1', status: 'success', downstream: response.data });
    } catch (error) {
        logger.error(`Error communicating with Backend 2: ${error.message}`);
        res.status(502).json({ error: 'Bad Gateway', details: error.message });
    }
});

app.listen(3001, () => logger.info('Backend 1 listening on port 3001'));