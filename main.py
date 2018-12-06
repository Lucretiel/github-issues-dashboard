from autocommand import autocommand
import aiohttp
import asyncio
import json
import collections

WHOAMI_QUERY = '''
query {
  viewer {
    login
  }
}
'''

ISSUES_QUERY = '''
query($owner:String! $repo:String! $cursor:String) {
  repository(owner:$owner name:$repo) {
    issues(first:100 after:$cursor states:[OPEN]) {
      nodes {
        title
        url
        number
        authorAssociation
        author {
        	login
        }
        assignees(first:100) {
          nodes {
            login
          }
        }
        labels(first:100) {
          nodes {
            name
          }
        }
        comments(last:1) {
          nodes {
            authorAssociation
            author {
              login
            }
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
'''


class Issue(collections.namedtuple("Issue", "title number url")):
	pass

async def get_my_login(*, session):
	full_query = {
		"query": WHOAMI_QUERY
	}

	async with session.post("https://api.github.com/graphql", json=full_query) as response:
		return (await response.json())["data"]["viewer"]["login"]


async def get_issues(*, session, owner, repository, ignore_labels, my_login):
	ignore_labels = {label.lower() for label in ignore_labels}

	async def get_page(cursor):
		full_query = {
			"query": ISSUES_QUERY,
			"variables": {
				"owner": owner,
				"repo": repository,
				"cursor": cursor
			}
		}
		async with session.post("https://api.github.com/graphql", json=full_query) as response:
			data = await response.json()

		issues_data = data["data"]["repository"]["issues"]
		issues = issues_data["nodes"]
		pageInfo = issues_data["pageInfo"]
		cursor = pageInfo['endCursor'] if pageInfo['hasNextPage'] else None

		return (cursor, issues)

	request = get_page(None)

	while request is not None:
		(cursor, issues) = await request

		if cursor:
			request = asyncio.ensure_future(get_page(cursor))

			# Allow the next request to initiate, so i/o is happening in the
			# background
			await asyncio.sleep(0)
		else:
			request = None

		for issue in issues:
			# Always show it if I'm assigned
			#assignees = (assignee["login"] for assignee in issue["assignees"]["nodes"])
			#if my_login not in assignees:
			# Check ignore_labels, commentor status
			if any(
				label["name"].lower() in ignore_labels
				for label in issue["labels"]["nodes"]
			):
				continue

			# Ignore stuff that I reported myself
			if issue["authorAssociation"] in ("MEMBER", "OWNER", "COLLABORATOR"):
				continue

			if issue["author"]["login"] == my_login:
				continue

			# Ignore stuff that I am the most recent commentor
			comments = issue["comments"]["nodes"]
			if comments:
				if comments[0]["authorAssociation"] in ("MEMBER", "OWNER", "COLLABORATOR"):
					continue
				if comments[0]["author"]["login"] == my_login:
					continue


			yield Issue(
				title=issue["title"].strip(),
				url=issue["url"],
				number=issue["number"],
			)


@autocommand(__name__, loop=True)
async def main(
	owner,
	repository,
	token: "Github API token" =None,
	ignore_labels:
		"Space separated list of github issue labels to ignore (defaults to '%(default)s')"
		="snooze internal-bug"
):
	'''
	This script is designed to produce a list of github issues on a repository
	that are in need of attention. Currently, this is defined as Issues to which
	you are assigned, or issues for which you or a maintainer are NOT the most
	recent commentor. It also currently ignores issues which you reported, as
	it's intended to be an aid in ensuring community responsiveness.
	'''
	headers = {
		"Authorization": "bearer {token}".format(token=token),
		"Accept": "application/json",
		"Content-Type": "application/json",
	}

	async with aiohttp.ClientSession(headers=headers) as session:
		my_login = await get_my_login(session=session)

		async for issue in get_issues(
			session=session,
			owner=owner,
			repository=repository,
			ignore_labels=ignore_labels.split(),
			my_login=my_login,
		):
			print("Issue {number}\t{title}".format(
				number=issue.number,
				title=issue.title,
			))
