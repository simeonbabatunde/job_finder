The overall goal of this app is for it to be able to apply to jobs (say on linkedin for a start) that match the uploaded resume and other information automatically. I want create an LLM that will take and analyze the resume, check each job postings and submit an application to those (maybe top 10 first start, there should be a way to select more on the webpage for subscribed users) that match the skills in the resume. The llm can be built using langgraph and I want it to support both enterprise LLM api calls from OpenAI and others, as well as local LLM deployed via ollama. The app should have a subscription model where users can subscribe to get access to more job postings and other features. The app should penable the user to see the history of job applications submitted and the status of each application. Remember the tech stack currently being used in the app, including Docker-compose, uv etc.

The auto apply section of the app should be placed below the resume upload section and the job preferences section. I dont think there should be a separate button for Analyse Resume and Save preferences as the user will click on the auto apply button to do both.
Also limit the application History displayed to the most recent 5 applications. A more button should be added to view the rest of the applications on a new page.

Next Steps
 Real Search Integration: Replace the mock search node with a real LinkedIn/Indeed scraper.
 Enhanced Subscription Logic: Implement actual payment gateways and hard-limit applications for free users.
 Feedback Loop: Allow users to "Thumbs Up/Down" applications to improve the agent's matching accuracy.


OpenRouter API Key:
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