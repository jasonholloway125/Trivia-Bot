import datetime as dt
import discord as disc
from discord.ext import tasks
import openai
import logging as log
import sys
import os
import json



class TriviaBot(disc.Client):
    def __init__(self, intents: disc.Intents, openai_key: str) -> None:
        super().__init__(intents=intents)
        self.__initialize_logging__()
        openai.api_key = openai_key
        self.__logger.debug('OpenAI key set.')

        self.__initial_prompt = """
        You are a Discord bot that will provide unique trivia questions and answers to Discord users.
        I am the administrator, and I will send you two prompts: a prompt to change the category of 
        trivia questions and answers, and a prompt to ask for a new question and corresponding answer.

        When I prompt you to change the category, the message I will send you will look like: 
        "Change category to category_name.", 
        where category_name will be the category chosen by the Discord user. If the category seems 
        inappropriate or too obscure, you MUST respond with: 
        "The chosen category was too obscure or not appropriate. Please choose another category."
        If the category is acceptable and trivia questions can reasonably be found for this category,
        you MUST respond with: 
        "The category category_name has been selected.", 
        except category_name must be changed to the category_name that was sent to you in the prompt.

        When I prompt you to send a new question and answer, the message I will send you will look like:
        "Find a new and unique question and answer for the chosen category."
        You MUST respond with a new question and answer in the following format:
        {"question": "insert_question", "answer": "insert_answer"}
        You MUST replace insert_question with the trivia question you have chosen, and you MUST replace
        insert_answer with the corresponding answer. The intention is to convert your response into a Python
        dictionary. You MUST not change anything else from the above format.
        """

        self.__conversations = {}
        self.__categories = {}
        self.__qa = {}


    def __initialize_logging__(self):
        self.__logger = log.Logger('Trivia Bot')
        self.__logger.handler = log.StreamHandler(sys.stdout)
        self.__logger.handler.setLevel(log.DEBUG)
        formatter = log.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        self.__logger.handler.setFormatter(formatter)
        self.__logger.addHandler(self.__logger.handler)
        
        path = "{0}\{1}".format(os.getcwd(), "logs")
        if not os.path.exists(path):
            os.makedirs(path)
        file_path = "{0}\{1}.log".format(path, dt.datetime.now().strftime("%Y-%m-%d"))
        
        f_logger = log.FileHandler(file_path)
        f_logger.setLevel(log.DEBUG)
        f_logger.setFormatter(log.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.__logger.addHandler(f_logger)

        self.__logger.debug('Logger initialized.')


    async def send_msg(self, channel: disc.TextChannel, message: str):
        self.__logger.debug(f'Sending message "{message}" to {channel.name} of #{channel.guild.id}')
        self.__initialize_logging__()
        await channel.send(message)


    async def on_guild_join(self, guild: disc.Guild):
        self.__logger.info(f'Added to #{guild.id}')

        old_channel = self.__get_oldest_channel__(guild)
        self.__logger.debug(f'Found oldest channel of #{guild.id}: {old_channel.id}')

        await self.send_msg(old_channel, "Thank you for adding Trivia Bot! For a list of commands, please enter **!trivia help**.")


    async def on_guild_remove(self, guild: disc.Guild):
        self.__logger.info(f'Removed from #{guild.id}')


    async def on_ready(self):
        self.__logger.info(f'Logged in as {self.user}')

        await self.__clear_conversation__.start()    


    async def on_message(self, message: str):
        if message.author == self.user:
            return
        
        msg: str = message.content.strip().lower()
        if msg.startswith('!trivia'):
            self.__logger.debug(f'Received !trivia message#{message.id} from #{message.guild.id}.')

            msg = msg[7:].strip()
            if len(msg) == 0:
                self.__logger.debug(f'Message#{message.id} is empty.')
                
                await self.send_msg(message.channel, 'Hello! Please use **!trivia help** to see the list of available commands.')
            elif msg == 'help':
                self.__logger.debug(f'Message#{message.id} is for getting help.')

                await self.send_msg(message.channel, '## Trivia Bot Commands\n'
                                        '**!trivia c *category_name***: change the trivia category.\n'
                                        '**!trivia nq**: display the next question.\n'
                                        '**!trivia q**: display the current question.\n'
                                        '**!trivia a**: display the current question\'s answer.\n'
                                        '**!trivia tc**: display the current trivia category.\n'
                                        '**!trivia help**: display the list of available commands.')
            elif msg == 'nq':
                if self.__categories.get(message.guild.id) is None:
                    self.__logger.debug(f'Message#{message.id} is for the next question but no category has been set.')

                    await self.send_msg(message.channel, "No category has been set. Please use **!trivia c *category_name*** to set a category.")
                else:
                    response = self.__get_chatgpt_response__("Find a new and unique question and answer for the chosen category.", message.guild.id)
                    if self.__filter_qa_response__(response, message.guild.id):
                        self.__logger.debug(f'Message#{message.id} is for next question.')

                        await self.send_msg(message.channel, self.__qa[message.guild.id]['question'])
                    else:
                        self.__logger.debug(f'Message#{message.id} is for next question but question failed to load.')

                        await self.send_msg(message.channel, 'A trivia question failed to be found. Please repeat command or change category.')
            elif msg == 'q' or msg == 'a':
                if self.__qa.get(message.guild.id) is None:
                    self.__logger.debug(f'Message#{message.id} is for the current q&a but no q&a is loaded.')

                    await self.send_msg(message.channel, "No questions have been asked. Please use **!trivia nq** to load a new question.")
                else:
                    if msg == 'q':
                        self.__logger.debug(f'Message#{message.id} is for the current question.')

                        await self.send_msg(message.channel, self.__qa[message.guild.id]['question'])
                    else:
                        self.__logger.debug(f'Message#{message.id} is for the current answer.')

                        await self.send_msg(message.channel, self.__qa[message.guild.id]['answer'])
            elif msg == 'tc':
                if self.__categories.get(message.guild.id) is None:
                    self.__logger.debug(f'Message#{message.id} is for the current category but no category has been set.')

                    await self.send_msg(message.channel, "No category has been set. Please use **!trivia c *category_name*** to set a category.")
                else:
                    self.__logger.debug(f'Message#{message.id} is for the current category.')

                    await self.send_msg(message.channel, f"### Category:\n{self.__categories[message.guild.id]}")
            elif msg.startswith('c'):
                category = msg[1:].strip().upper()

                if len(category) == 0:
                    self.__logger.debug(f'Message#{message.id} is for changing category but the category is empty.')
                    return

                self.__logger.debug(f'Message#{message.id} is for changing category to {msg}.')

                response = self.__get_chatgpt_response__(f"Change category to {category}.", message.guild.id)
                await self.send_msg(message.channel, self.__filter_category_reponse__(category, response, message.guild.id))
            else:
                self.__logger.debug(f'Message#{message.id} is unknown.')

                await self.send_msg(message.channel, f'**"{msg}"** is an unknown command. Please use **!trivia help** to see the list of available commands.')


    def __get_oldest_channel__(self, guild: disc.Guild) -> disc.TextChannel:
        old_cha = None
        for channel in guild.text_channels:
            if old_cha is None or channel.created_at < old_cha.created_at:
                old_cha = channel
        return old_cha


    def __add_conversation__(self, guild_id: int):
        self.__logger.debug(f'Added #{guild_id} to active conversations.')

        self.__conversations[guild_id] = {
            "last_updated": dt.datetime.now(),
            "messages": [{"role": "system", "content": self.__initial_prompt}]}
        

    @tasks.loop(seconds=24)
    async def __clear_conversation__(self):
        now = dt.datetime.now()
        for key, value in self.__conversations.items():
            dif: dt.timedelta = now - value['last_updated']
            if dif.seconds > 86340:
                self.__remove_conversation__(key)


    def __remove_conversation__(self, guild_id: int):
        self.__logger.debug(f'Removed #{guild_id} from active conversations.')

        del self.__conversations[guild_id]
        del self.__qa[guild_id]
        del self.__categories[guild_id]
    

    def __filter_category_reponse__(self, category: str, response: str, guild_id: int) -> str:
        response = response.strip()
        
        self.__logger.debug("ChatGPT Category Response: " + response)

        if not (response.startswith("The category") and response.endswith("has been selected.")):
            return "The chosen category was too obscure or not appropriate. Please choose another category."
        response = "### " + response
        self.__categories[guild_id] = category
        return response
    
    
    def __filter_qa_response__(self, response: str, guild_id: int) -> bool:
        self.__logger.debug("ChatGPT QA Response: " + response)

        try:
            qa: dict = json.loads(response)
            if qa.get('question') is None or qa.get('answer') is None:
                raise ValueError
            qa['question'] = '## "{0}" TRIVIA QUESTION:\n### {1}'.format(self.__categories[guild_id], qa['question'])
            qa['answer'] = '## "{0}" TRIVIA ANSWER:\n### {1}'.format(self.__categories[guild_id], qa['answer'])
            self.__qa[guild_id] = qa
            return True
        except ValueError:
            return False


    def __update_conversation_time__(self, guild_id: int):
        if self.__conversations.get(guild_id) is None:
            return
        self.__conversations[guild_id]['last_updated'] = dt.datetime.now()


    def __get_chatgpt_response__(self, msg: str, guild_id: int) -> str:
        if self.__conversations.get(guild_id) is None: 
            self.__add_conversation__(guild_id)
        self.__conversations[guild_id]['messages'].append({"role": "user", "content": msg})
        response = openai.ChatCompletion.create(
            model = "gpt-3.5-turbo-0301",
            messages = self.__conversations[guild_id]['messages']
        )

        self.__logger.debug("Received message from ChatGPT.")

        refined = response["choices"][0]["message"]["content"]
        self.__conversations[guild_id]['messages'].append({"role": "assistant", "content": refined})
        self.__update_conversation_time__(guild_id)
        return refined



if __name__ == '__main__':
    openai_key = "PUT OPENAI KEY HERE"
    discord_token = 'PUT DISCORD APPLICATION TOKEN HERE'

    intents = disc.Intents.default()
    intents.message_content = True

    client = TriviaBot(intents=intents, openai_key=openai_key)
    client.run(discord_token)